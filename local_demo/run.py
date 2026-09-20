"""Exercise the real upstream agent loop; scripted mode is not an LLM benchmark."""

import argparse
import json
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv

from smolagents import Model, OpenAIServerModel, Tool, ToolCallingAgent
from smolagents.models import ChatMessage, ChatMessageToolCall, ChatMessageToolCallFunction, MessageRole


ROOT = Path(__file__).resolve().parents[1]


class OrderTool(Tool):
    name = "get_order"
    description = "Look up an order and return its SKU and shipping status."
    inputs = {"order_id": {"type": "string", "description": "Order identifier, e.g. ORDER_001."}}
    output_type = "string"

    def forward(self, order_id: str) -> str:
        if order_id != "ORDER_001":
            raise ValueError(f"Unknown order: {order_id}")
        return json.dumps({"order_id": order_id, "sku": "SKU_A", "status": "unshipped"})


class InventoryTool(Tool):
    name = "get_inventory"
    description = "Return stock for a SKU obtained from an order. A temporary failure may be retried once."
    inputs = {"sku": {"type": "string", "description": "A SKU identifier, not an order identifier."}}
    output_type = "string"

    def __init__(self, transient_failure: bool = False):
        super().__init__()
        self.transient_failure = transient_failure
        self.attempts = 0

    def forward(self, sku: str) -> str:
        self.attempts += 1
        if sku != "SKU_A":
            raise ValueError(f"Unknown SKU: {sku}")
        if self.transient_failure and self.attempts == 1:
            raise TimeoutError("TemporaryUnavailable: retry this read-only call once")
        return json.dumps({"sku": sku, "available": 7})


class ScriptedModel(Model):
    """A known transcript tests framework plumbing without an API key or downloaded model."""

    def __init__(self, fault: bool = False):
        super().__init__(model_id="scripted-integration-fixture")
        self.calls = 0
        self.actions = [("get_order", {"order_id": "ORDER_001"}), ("get_inventory", {"sku": "SKU_A"})]
        if fault:
            self.actions.append(("get_inventory", {"sku": "SKU_A"}))
        self.actions.append(("final_answer", {"answer": {"order_id": "ORDER_001", "sku": "SKU_A", "available": 7}}))

    def generate(self, messages, **kwargs):
        if self.calls >= len(self.actions):
            raise RuntimeError("Fixture exceeded its expected transcript")
        name, arguments = self.actions[self.calls]
        self.calls += 1
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content="Scripted integration fixture; no LLM inference.",
            tool_calls=[
                ChatMessageToolCall(
                    id=f"call_{self.calls}",
                    type="function",
                    function=ChatMessageToolCallFunction(name=name, arguments=arguments),
                )
            ],
        )


def run_case(mode="scripted", fault=False):
    if mode == "scripted":
        model = ScriptedModel(fault=fault)
    else:
        load_dotenv(ROOT / ".env", override=False)
        missing = [name for name in ("MODEL_ID", "OPENAI_API_BASE", "OPENAI_API_KEY") if not os.getenv(name)]
        if missing:
            raise ValueError("Configure .env first: " + ", ".join(missing))
        model = OpenAIServerModel(
            model_id=os.environ["MODEL_ID"],
            api_base=os.environ["OPENAI_API_BASE"],
            api_key=os.environ["OPENAI_API_KEY"],
            max_tokens=512,
            client_kwargs={"timeout": 60.0, "max_retries": 0},
        )
    inventory = InventoryTool(transient_failure=fault)
    agent = ToolCallingAgent(
        tools=[OrderTool(), inventory], model=model, max_steps=5, max_tool_threads=1, verbosity_level=0
    )
    result = agent.run(
        "Find the SKU for ORDER_001, then check stock. Return final_answer with a JSON object "
        "containing exactly order_id, sku, available. Retry a temporary tool failure once.",
        return_full_result=True,
    )
    output = result.output
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            pass
    expected = {"order_id": "ORDER_001", "sku": "SKU_A", "available": 7}
    return {
        "mode": mode,
        "scope": "integration_smoke_only" if mode == "scripted" else "single_task_api_smoke",
        "fault": fault,
        "passed": output == expected,
        "output": output,
        "inventory_attempts": inventory.attempts,
        "run": result.dict(),
        "upstream_commit": subprocess.check_output(["git", "rev-parse", "upstream/main"], cwd=ROOT, text=True).strip(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["scripted", "api"], default="scripted")
    parser.add_argument("--fault", action="store_true")
    args = parser.parse_args()
    report = run_case(args.mode, args.fault)
    destination = ROOT / "artifacts" / f"{args.mode}-{'fault' if args.fault else 'clean'}.json"
    destination.parent.mkdir(exist_ok=True)
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")
    print(json.dumps({"passed": report["passed"], "mode": args.mode, "report": str(destination)}, ensure_ascii=False))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
