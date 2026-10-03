# 八个轨迹案例

八个案例从已保留的首次尝试中有意选择，由分析器同一作者核验，不是随机样本或独立人工标注。案例用于解释具体行为，不估计总体发生率。

消息索引采用原始轨迹的零起始索引。case_index.json保存来源哈希、选定消息的角色、去掉参数值的工具事件和冻结指标；语义判断仍需本地完整轨迹。

## C01 用户在首次WRITE确认时结束

`formal-t26-U0-r1` · attempt 0 · `valid` · messages `[16, 17]`

末尾用户消息17明确要求执行return并含STOP；轨迹只有六次READ且没有return工具调用，DB和最终reward为0。

解释：说明User结束与尚未执行WRITE同时出现；未运行反事实，不能把全部差异归因于Simulator。

Outcome SHA256: `617c690ffb46e289fcdc54ddf1e66ecfa6f46dbbe5777fa3a43ca83a04578a99`

## C02 已改变状态后的第二种WRITE被拒绝

`formal-t27-U2-r1` · attempt 0 · `valid` · messages `[22, 23, 24, 25, 26, 27, 28, 29]`

消息22–23先return成功；24–25 exchange报Non-delivered order cannot be exchanged；后续transfer成功但DB reward仍0。

解释：参数相同失败重复不是本例原因；业务动作顺序与订单状态有关。不能把transfer成功等同任务成功。

Outcome SHA256: `ffabba77310b51ca386facad18b61befe6468dbe20a75955b32f3d3e04bf87f9`

## C03 成功READ重复与遗漏最后WRITE

`formal-t32-U0-r0` · attempt 0 · `valid` · messages `[28, 29, 32, 33, 35, 36, 37]`

两次cancel成功，参考三种WRITE只匹配两种；最后用户消息37确认return且STOP，未执行return。跨轮精确重复为一次成功get_order_details。

解释：重复计数不等于故障重复；目前failed-call Guard不会拦截成功READ。

Outcome SHA256: `b7f8e79dadb6bbb7589f6e3c25c8d421179d5ac74e075469514f9ecf3a88fad7`

## C04 错误后合法换路径恢复

`formal-t36-U0-r0` · attempt 0 · `valid` · messages `[4, 5, 6, 7, 8, 9, 30, 31, 34, 35]`

消息4–5 email查找失败；Agent在6询问其它身份信息，8–9使用name/zip成功；30–31修改pending items成功，DB与最终reward均1。

解释：native Agent自身已能合法恢复。本例不能据此给Toy Guard归因。

Outcome SHA256: `72d7cb79d4851a1605982592a0a536d16a9328ff92c365c45276ac8b46ba30a0`

## C05 评估器解析失败

`formal-t39-U0-r0` · attempt 0 · `infrastructure_error` · messages `[16, 17]`

simulation已保存；evaluator三次parse_attempt均JSONDecodeError且invalid_response以Markdown代码围栏开头；reward为空。

解释：属于评估基础设施无效，不填reward-zero。User末尾还有确认STOP，但没有有效官方评分，不能纳入成功率。

Outcome SHA256: `8b7eb41e60474496368be6575b7854fc3be8926137eef9fa186ff0c83cbeb746`

## C06 User输出截断关联执行无效

`formal-t40-U0-r1` · attempt 0 · `infrastructure_error` · messages `[10, 11, 12]`

最后User请求finish_reason=length，completion8194且reasoning8192，随后simulation阶段ValueError；官方reward为空。

解释：日志支持截断与错误相关，尚未记录足够错误文本证明完整因果；不修改冻结8192生成上限。

Outcome SHA256: `b05a026c61aaf9157249c6e5aba7c504b19def0e6d622de027555041aa105f8f`

## C07 部分WRITE完成后的终止漏检边界

`formal-t55-U0-r0` · attempt 0 · `valid` · messages `[24, 25, 26, 27, 30, 31, 32, 33]`

四个参考WRITE已匹配三个；末尾User33确认第四个return并结束；最终reward0，但confirmation_terminal_before_write_candidate=False。

解释：该字段要求尚未完成任一参考WRITE，因此不覆盖部分完成后的最后WRITE遗漏。报告不能把False当作没有终止影响。

Outcome SHA256: `2bae5b2ee1c2e9b09a29a4bb17c6f5644781f82b0743ad17df4af7e1073397bd`

## C08 预算纠正导致的人工取消

`formal-t62-U2-r2` · attempt 0 · `timeout` · messages `[0]`

仅保存初始assistant消息0；第一个User HTTP因StudyDeadline中断且usage缺失，worker status=timeout。

解释：这是操作中断，不能算模型失败；原费用预留保留。agent_after_terminal_user=True在无User/terminal NONE时也出现，字段只在实际terminal存在时有对应含义。

Outcome SHA256: `93304363034e21ec4fc1210d096341c1695e7b3fa54e584ab002974021e83091`

这些轨迹中没有部署Toy Guard。工具机制证据、Simulator敏感性和原生Agent效果分别解释；首次无效与操作取消保留原始状态和费用。
