# Design Principles

1. **Replay before emulation.** Có output NocPro quan sát thật thì replay, không tính lại để “trông giống”.
2. **Raw preserved, canonical added.** Normalize không được phá raw source.
3. **Real before synthetic.** Synthetic chỉ lấp capability/test gap.
4. **Golden fixtures immutable.** Scenario synthetic phải clone/mutate có nhãn, không sửa Golden.
5. **Fail closed.** Thiếu mapping/semantics/quality ⇒ UNKNOWN / UNAVAILABLE, không đoán.
6. **System Fact ≠ Explain Evidence.** Mock không được biến NocPro score/config thành normalized evidence của downstream.
7. **Transport-neutral.** Direct Snapshot trước; Kafka chỉ adapter.
8. **Deterministic.** Scenario synthetic có seed/config/generation rule.
9. **No circular validation.** Synthetic/backfill/unknown-usage không được masquerade as independent validation.
10. **No fake model internals.** Không tạo `A_ij`, ΔQ, node movement nếu source không có.
