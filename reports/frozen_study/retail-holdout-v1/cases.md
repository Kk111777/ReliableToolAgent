# Eight trajectory cases

These eight first-attempt cases were purposively selected and inspected by the analyzer author. They are not a random sample or independent annotation, and do not estimate population rates.

Message indices are zero-based positions in the retained trajectory. case_index.json records hashes, selected message roles, tool events without argument values and frozen metrics. Semantic interpretations still require the retained local trajectory.

## C01 User stops at the first WRITE confirmation

`formal-t26-U0-r1` · attempt 0 · `valid` · messages `[16, 17]`

At message 17 the User confirms the return and emits STOP. The retained trajectory contains six READ calls and no return WRITE; DB and final reward are zero.

Interpretation: Termination and the missing WRITE co-occur. No counterfactual run establishes that the Simulator alone caused the result.

Outcome SHA256: `617c690ffb46e289fcdc54ddf1e66ecfa6f46dbbe5777fa3a43ca83a04578a99`

## C02 A WRITE changes the state before a second WRITE is rejected

`formal-t27-U2-r1` · attempt 0 · `valid` · messages `[22, 23, 24, 25, 26, 27, 28, 29]`

Messages 22–23 complete a return. The following exchange is rejected because the order is no longer in the required delivered state. Transfer then succeeds, while DB reward remains zero.

Interpretation: The tool error concerns business state and action order. A successful transfer does not establish completion of the original task.

Outcome SHA256: `ffabba77310b51ca386facad18b61befe6468dbe20a75955b32f3d3e04bf87f9`

## C03 A successful READ repeats before the final WRITE is omitted

`formal-t32-U0-r0` · attempt 0 · `valid` · messages `[28, 29, 32, 33, 35, 36, 37]`

Two cancellations complete, matching two of three reference WRITE keys. Message 37 confirms a return and emits STOP; no return follows. The exact cross-turn repeat is a successful get_order_details call.

Interpretation: An exact repeat is not necessarily a repeated failure. The toy failed-call Guard does not target successful READs, and it was not deployed in this native run.

Outcome SHA256: `b7f8e79dadb6bbb7589f6e3c25c8d421179d5ac74e075469514f9ecf3a88fad7`

## C04 The native Agent recovers through another lookup path

`formal-t36-U0-r0` · attempt 0 · `valid` · messages `[4, 5, 6, 7, 8, 9, 30, 31, 34, 35]`

An email lookup fails at messages 4–5. The Agent asks for other identifying details at 6 and succeeds through a name/ZIP lookup at 8–9. The later pending-items WRITE succeeds; DB and final reward are one.

Interpretation: This is recovery by the unchanged native Agent. It does not establish a benefit from the separate toy Guard.

Outcome SHA256: `72d7cb79d4851a1605982592a0a536d16a9328ff92c365c45276ac8b46ba30a0`

## C05 Evaluator JSON parsing fails

`formal-t39-U0-r0` · attempt 0 · `infrastructure_error` · messages `[16, 17]`

The simulation is retained, but all three evaluator parse attempts raise JSONDecodeError. Their outputs begin with Markdown fences; official reward is null.

Interpretation: This is an invalid evaluation, not a scored reward-zero task. The terminal confirmation in the trajectory cannot substitute for a valid official score.

Outcome SHA256: `8b7eb41e60474496368be6575b7854fc3be8926137eef9fa186ff0c83cbeb746`

## C06 A truncated User output accompanies a simulation error

`formal-t40-U0-r1` · attempt 0 · `infrastructure_error` · messages `[10, 11, 12]`

The last User call ends with finish_reason=length, 8194 completion tokens and 8192 reasoning tokens. The simulation then records ValueError; official reward is null.

Interpretation: The logs show an association. They do not establish the entire causal chain, and the frozen output limit was not changed.

Outcome SHA256: `b05a026c61aaf9157249c6e5aba7c504b19def0e6d622de027555041aa105f8f`

## C07 A remaining WRITE falls outside the frozen candidate rule

`formal-t55-U0-r0` · attempt 0 · `valid` · messages `[24, 25, 26, 27, 30, 31, 32, 33]`

Three of four reference WRITE keys match. At message 33 the User confirms the final return and stops; final reward is zero, but confirmation_terminal_before_write_candidate is false.

Interpretation: The frozen rule requires that none of the reference WRITE keys succeeded. False therefore does not exclude termination after partial completion.

Outcome SHA256: `2bae5b2ee1c2e9b09a29a4bb17c6f5644781f82b0743ad17df4af7e1073397bd`

## C08 An operational cancellation is retained as a timeout

`formal-t62-U2-r2` · attempt 0 · `timeout` · messages `[0]`

Only the initial assistant message is retained. The first User request is cancelled during a budget correction; usage is missing and the frozen worker records timeout/StudyDeadline.

Interpretation: The cancellation is not a scored model failure. Its usage reserve remains. agent_after_terminal_user is true despite no User message and terminal NONE, illustrating the field coverage limit.

Outcome SHA256: `93304363034e21ec4fc1210d096341c1695e7b3fa54e584ab002974021e83091`

The toy Guard was not deployed in these trajectories. Tool mechanisms, Simulator sensitivity and native Agent outcomes remain separate claims. Invalid first attempts and operational cancellations retain their original status and cost.
