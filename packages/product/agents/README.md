# agents

Phase 6 の 8 役割（Macro／Fundamental／Quant／Composer／Strategist／PM／Trader／Risk）を、
狭い immutable message interface で実装する。

Agent は secrets、raw J-Quants、SQLite/PIT handle、HTTP client を受け取らない。
Strategist の出力は宣言的 `StrategySpec` のみで、trusted interpreter が approved feature の
`ctx.feature` 呼び出しへ変換する。Trader は Paper plan のみを作り、broker には接続しない。
全 interface と境界は [docs/agents.md](../docs/agents.md) を参照。
