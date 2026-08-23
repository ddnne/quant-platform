# Original 08-20/22 plan vs current tree

> **Pointer (not a rewrite).** Register still holds at `208df8ec`; AND product still stopped (`CATALOG_AND_PLUS_N_STOPPED=True`); remaining original-plan work is still human reconstitution (`RECONSTITUTION_APPLY=False`); Phase 7 still **NO-GO**. The body below is a freeze at `e927b97`.

**Lane:** historian/auditor (isolation worktree; docs only)  
**Tree at authoring:** `e927b97` (`docs/original-plan-gap`)  
**Live residual:** [`../phase62_residual_status.md`](../phase62_residual_status.md)  
**Recording ADR:** [`../architecture/adr_research_recording.md`](../architecture/adr_research_recording.md)  
**Compaction (read-only):** `segment_030.md`–`segment_032.md` plus INDEX (08-20/21 recording reset; 08-22 combination/funds; AND-enumeration; `CATALOG_AND_PLUS_N_STOPPED`)

Mass / READY / Phase 7 / operational GO remain **NO-GO / 未宣言 / OFF**. This note does **not** GO, does **not** recommend YAML `+N`, and does **not** recommend AND as a product.

Sources used: compaction 030–032 (standing briefs and the 17:25/course-correction turns); `eval_flags.py`; `phase62_residual_status.md`; `phase63_refactor_plan.md`; `phase63_reconstitution_pending.md`; ADR recording. Compaction files were **not** modified.

---

## Direction-correction register / 方向修正レジスタ

| # | Item / 項目 | Original valid? / 当初は妥当か | Still held? / 今も保持 | Direction correction needed? / 方向修正 |
|---:|-------------|-------------------------------|------------------------|------------------------------------------|
| 1 | 08-20/21 recording reset | **Yes / 妥当** | **Yes / 保持** | **No / 不要** |
| 2 | 08-22 combination/funds + usable-net metric | **Yes / 妥当** | **Partial / 部分保持** (funds thesis kept; YAML-as-product abandoned) | **No further / 追加不要** (AND product already cut) |
| 3 | AND-enumeration / YAML product / `+N` without Worker bodies | **Invalid deviation / 無効逸脱** | Stopped (`CATALOG_AND_PLUS_N_STOPPED`; YAML n=0; compiled n=2254) | **No / 不要** — correction already valid |
| 4 | HOLD leftovers (occupancy, unique22, live math, factory OFF, 3 pins, PARSE_ZERO 2, cheap_pb) | Not a deviation / 逸脱ではない | **Yes / 保持** | **No / 不要** (do not “clean up”) |
| 5 | Architecture convergence (fail-closed Worker, Evaluation IR, receipt authority, Gateway) | Not in 08-22 product brief / 08-22 製品ブリーフには無い | Landed as **ops product** after Mass was display-only | **No product pivot / 製品ピボットではない** — valid addition |
| 6 | Remaining original-plan work | Human reconstitution KEEP 24df | Pending (`RECONSTITUTION_APPLY=False`) | **No / 不要** — do not substitute YAML / Mass / Phase 7 |
| 7 | Next phase = Mass / READY / Phase 7 GO | Never the original next step / 当初から次ではない | **NO-GO** | **No / 禁止** — do not declare GO |

---

## 1. Original 08-20/21 plan — recording reset

**JA.** 08-20 は W99–W107 の `scripts/run_wNN_*.py` + `docs/proof/w08*_wNN_*.md` を評価倉庫にしていた。08-21 ADR（Accepted）はその倉庫を止め、役割を分けた: **Git = コード / 契約 / カタログ / 薄いライブ residual**; **スコア SoT = Cloudflare R2 + D1**（`quant-structured/research/eval/job={id}/`、D1 は job/cell 索引のみ）。新規 `run_w` と proof スコアカードは禁止。candidate-grade は `POST /v1/daily-path`。period-net は bar-native 補助。Mass / READY / Phase 7 / 3-pin リチューン / PARSE_ZERO invent は当時から禁止。

**EN.** The 08-21 recording reset is **valid** and **still held**. Residual is live flags only (`phase62_residual_status.md`). No `scripts/run_wNN_*.py` remain. Scores are not restated into Git markdown. Candidate SoT is still daily-path. Catalog identity is code (`specs/research_catalog/` compiled n=2254), not a wave warehouse.

**Correction?** **No.** Do not revive `run_w` or proof warehouses.

---

## 2. Original 08-22 plan — combination/funds from simple gated theses

**JA.** 08-22 09:06 の本筋は、単純・疎な gated theses を **後の combination / funds の材料として残す**こと。厳しい単体 t/Sharpe 床で母集団を痩せさせない。YAML は **宣言**（combo のゲート宣言 + Worker body + occupancy-equal）であり、ファイル枚数そのものが製品ではない。candidate から path_broken / always_on（occ≥0.85）/ near_empty（occ≤0.05）を外す。ヘッド N 禁止。GO するな。

メトリックを「単独の強さ」から **usable net / occupancy 帯**（`USABLE_OCCUPANCY_MIN=0.12`、material (0.12, 0.85)、thin は sleeve から除外）へ移したことは **妥当**。usable inventory `eval-usable-inventory-20260824ev` n_usable 1880 はその測定であり、合格宣言ではない。

**EN.** Combination/funds from **simple gated theses** is still the research product. YAML-as-declaration was the 08-22 design; YAML-as-inventory was not. The metric shift to usable net / occupancy-honest candidate policy is **valid** and **still held**. Sleeve majority is never a pass. `primary_candidate` ≠ GO.

**Correction?** **No** on the funds premise or the usable-net metric. The correction is only against treating combinatorial YAML as the product (item 3).

---

## 3. Invalid deviation — AND-enumeration / YAML product / `+N` without Worker bodies

**JA.** 大きな無効逸脱は **AND 列挙を在庫製品にしたこと**、および **Worker body 無しの `+N` YAML**。08-22 15:23 以降のゲート順列・カタログ増産は、当初の「単純 theses を combo/funds に組み合わせる」を **組み合わせ地図の埋め尽くし**に読み替えた。usable 1780→1830→1880 の vol/flow **bounded fill** までは地図穴として成立する。881 件級の 3-AND と YAML 2254 は「宣言」を超える。rate の tag_count を同じ `+50` で埋めるのは逸脱の継続なので切った。

すでに入った是正:

- `CATALOG_AND_PLUS_N_STOPPED=True` / `EVENT_THREE_AND_PLUS_N_STOPPED=True`（`eval_flags.py`; 17:25 で一度外して flow +50 を入れ、`8cc38fc` で再固定）
- YAML 機械削除（`5c9b962`; `yaml_still_present: false`）
- freeze identity **compiled n=2254**（`CATALOG_YAML_COUNT_AT_STOP`; digest `sha256:6ad5ba57dfa41…`）
- known-thin unused 2-AND の再書き拒否; 3-AND 新規バッチ拒否
- countable = compiler row **+ Worker body + occupancy-equal**（YAML clone は数えない）

**EN.** AND-enumeration as product is the **large invalid deviation**. Course-correction is **valid** and must stay: do not flip the freeze without a dated brief; do not re-add YAML; do not treat rate tag_count as a fill mandate; do not resume `+N` without Worker bodies.

**Correction?** **No further.** Re-opening YAML `+N` or AND-as-product would be a **regression**, not a return to the original plan.

---

## 4. What is **not** a deviation / 逸脱ではないもの（HOLD）

These look like waste. They are **policy HOLD / SoT**, not dead code. Do not delete or unify to “clean the tree.”

| HOLD | Why it is not a deviation |
|------|---------------------------|
| Leftover occupancy in `daily_path.ts` | Unique-22 occupancy vs combo `pre_mom` `entryIdx-1`. Unifying with `comboEventGateOk` **rewrites occupancy**. Extract only as leftover **policy** after occupancy-equal re-eval (`phase63_refactor_plan.md` lane 3 HOLD). |
| unique22 park | `UNIQUE22_PARK_REASONS` (17 parked) + 5 occupancy-equal lifts. YAML is gone; park is code in `daily_path.ts`. Do not silent-unpark. |
| `cost_models.py` / `options_225_vol_series.py` keep-together | Live math. Size is not a split key. Fake-split numerator from denominator is a rewrite. |
| Factory `generation_enabled=False` (unique/combo) | Intentional. Offline factory stays OFF so propose/review refs do not break. Do not enable. |
| 3 pins frozen | `cross_section_hold_10` mom=5 **KEEP** · `cross_section_hold_10_mom3` mom=3 **PROMOTE** · `fundamentals_hold_10` **KEEP**. Not retuned. |
| PARSE_ZERO 2 | OTC `2002-08-02`, `2002-08-05` stay PARTIAL. Do not invent COMPLETE. |
| cheap_pb non-unify | `CHEAP_PB_EVENT_VS_CS = event_bars_x_fins_not_csfundsnaps`. Event cheap_pb is bars×fins, not CS fund snaps. Cap `CHEAP_PB_PRIMARY_GATE_CAP=0.20`. Do not unify event vs CS. |

**Correction?** **No.** Treating these as waste was the false “massive dead code” reading. The original plan already required them to stay.

---

## 5. Current vs original — architecture convergence is ops product, not a research pivot

**JA.** fail-closed Worker（`MASS_EVAL_TOKEN` 未設定は拒否; eval/propose は verified readiness なし 403）、Evaluation IR（`evaluation-ir/v1`）、receipt authority（verify-before-write / children-then-manifest / R2 create-if-absent）、AI Gateway（direct `env.AI` 禁止）は **08-22 の combination/funds ブリーフには無い**。これは Mass NO-GO が **表示だけ**だったことへの是正である（トークン無しで `/v1/mass-eval` 等が通る、Gateway を迂回する `env.AI.run`、不完全 cell でも `candidate_grade=true`）。

**EN.** Architecture convergence became necessary **after** Mass was display-only. It is the **ops product** that makes the 08-21 recording reset and the 08-22 “GO never” policy **mechanically true**. It is a **valid addition**, not a product pivot away from combination/funds. Gateway deployed ≠ Phase 7. Evaluation IR is grading authority, not a GO switch. Receipts do not mint Coverage COMPLETE.

**Correction?** **No pivot.** Keep building fail-closed honesty (4 PARTIAL, Projection STALE, `applied_cursor=null` never CURRENT). Do not narrate this work as Phase 7 or as a new research catalog.

---

## 6. Remaining original-plan work

**JA. 残る当初計画の本体は人間 reconstitution だけ。**

- `basket_theme_fund` / `basket_event_fund`: **human** が `drop_parents` vs `drop_children` を選ぶ（自動選択禁止）
- KEEP sleeve は `eval-cf-dp-both-sleeves-20260824df` のまま
- `RECONSTITUTION_APPLY` は人が dated brief で翻すまで **False**
- 24ek thinner を KEEP に戻さない
- occupancy preview はブレンドではない
- **YAML を足さない**
- **Mass / READY / Phase 7 GO を宣言しない**

**EN.** Next research product after the bounded vol/flow fills is **human reconstitution → KEEP sleeve member swap**, occupancy-conditioned, not more YAML, not AND product, not Mass/READY/Phase 7. `n_replacement_ok 0` is a fact, not a pass. Human main is not selected.

**Correction?** **No.** Do not substitute catalog growth or Phase 7 prep for the human cut.

---

## 7. Summary — is a direction change needed?

**Overall: no new direction change.** The only large invalid deviation (AND-enumeration / YAML-as-product / `+N` without bodies) is **already corrected**. Recording reset, usable-net metric, HOLD leftovers, and ops fail-closed are **in line** with 08-20/21/22 once Mass-as-display is treated as a defect to close, not as a research roadmap.

Do not:

- declare Phase 7 GO
- recommend YAML `+N`
- recommend AND as a product
- unpark unique22 / invent PARSE_ZERO COMPLETE / retune 3 pins / enable factory generation
- fake-split `cost_models` / `options_225` / leftover occupancy

Do:

- wait for human `drop_parents` vs `drop_children` on KEEP 24df
- keep `CATALOG_AND_PLUS_N_STOPPED` and compiled n=2254 freeze
- keep scores on R2+D1
- keep ops honesty (STALE projection, 4 PARTIAL, fail-closed Worker)
