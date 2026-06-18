# Snowball Strategy 実装仕様

## 1. 目的

- 両建てを基点に、順行側の回転利確と逆行側のカウンターエントリーで損益をならす。
- 逆行側はグリッド内のスロットにナンピン建玉を追加し、カウンターTPで新しい建玉から順に決済する。
- ロスカット、再建、証拠金保護、グリッド順序検証により、破綻しやすい状態を早期に止める。

この文書は現在の実装（`backend/apps/trading/strategies/snowball/`）に合わせた仕様である。

### 1.1 実装ファイル対応

| ファイル                | 役割                                                                |
| ----------------------- | ------------------------------------------------------------------- |
| `strategy.py`           | レジストリ連携、初期化、ティック処理、サイクルTP、実行結果反映。    |
| `config.py`             | 設定の正規化、既定値、検証、サブ設定オブジェクト。                  |
| `calculators.py`        | 間隔、カウンターTP、SL幅、再建TP幅、pips丸め。                      |
| `cycle_state.py`        | `SnowballStrategyState`、`SnowballCycle`、状態シリアライズ。        |
| `entries.py`            | `Entry` と `StopLossClosedEntry`。                                  |
| `grid_models.py`        | `PositionGrid`、`Layer`、`Slot`、スロット状態遷移。                 |
| `counter_flow.py`       | カウンター追加、カウンターTP、レイヤー初期TP。                      |
| `cycle_orchestrator.py` | サイクル処理順序、ステータス更新、再シード。                        |
| `stop_loss_flow.py`     | SL価格設定、SLクローズ、再建、再建TP/発動価格のclamp/伝播。         |
| `protection.py`         | 証拠金比率、Emergency、Shrink。                                     |
| `grid_policy.py`        | グリッドの建玉価格/TP順序検証、再建時の境界計算。                   |
| `pricing.py`            | 加重平均TP、レイヤー初期TP、約定価格反映時の価格同期。              |
| `accounting.py`         | NAV、未実現損益、証拠金比率メトリクス更新。                         |
| `execution_binding.py`  | 注文約定結果から `position_id`、fill price、trade cycle id を反映。 |
| `reconciliation.py`     | タスク再開時の broker ポジション照合。                              |
| `visualization.py`      | サイクル/グリッド可視化用の状態マップ。                             |
| `events.py`             | Open/Close/Rebuild イベントと Snowball 固有メタデータの付与。       |
| `parameters.py`         | レジストリ向けのパラメータ正規化・検証アダプタ。                    |
| `state_parsing.py`      | 永続化済み状態の厳格パース。                                        |

## 2. 前提と価格基準

### 2.1 前提

- 実行対象の通貨ペアと `pip_size` はタスク設定から渡される。例では `USD_JPY`、`pip_size=0.01` を使う。
- ヘッジ可能な口座では LONG と SHORT のサイクルを独立に初期化する。
- ヘッジ無効時は LONG のみで初期化し、SHORT サイクルは作成しない。
- FIFO 制約のある口座は想定していない。
- 両建て不可かつ FIFO 制約を受ける OANDA US 口座では、この戦略ではなく
  `docs/strategies/ja/snowball-net.md` の SnowballNet を使う。

### 2.2 価格基準

| 用途                     | LONG                     | SHORT                    |
| ------------------------ | ------------------------ | ------------------------ |
| 建玉価格                 | `ask`                    | `bid`                    |
| 決済価格                 | `bid`                    | `ask`                    |
| TP ヒット判定            | `bid >= close_price`     | `ask <= close_price`     |
| SL ヒット判定            | `bid <= stop_loss_price` | `ask >= stop_loss_price` |
| カウンター追加の逆行距離 | 現在の `ask` で計測      | 現在の `bid` で計測      |

逆行距離は `mid` ではなく、実際に新規建玉する側の価格で計測する。証拠金計算と一部の保護対象選択では `mid` を使う。

### 2.3 証拠金比率

実装上の証拠金比率は以下で計算する。

```
required_margin = mid * max(abs(long_units), abs(short_units)) * 0.04 * quote_to_account_rate
ratio = required_margin / NAV * 100
NAV = account_balance + unrealized_pnl
```

未実現損益は LONG を `bid`、SHORT を `ask` で評価する。`max(long_units, short_units)` を使うため、両建て時は OANDA の MAX 方式に近い扱いになる。

## 3. 主なパラメータ

### 3.1 コア

| パラメータ               | 既定値 | 説明                                                                                                   |
| ------------------------ | ------ | ------------------------------------------------------------------------------------------------------ |
| `base_units`             | `1000` | レイヤー内カウンターの基準通貨量。                                                                     |
| `trend_lot_size`         | `1`    | 初期エントリーとレイヤー初期エントリーのロット係数。実際の数量は `trend_lot_size * layer_base_units`。 |
| `m_pips`                 | `50`   | 初期 R0 の基本 TP 幅。再建後は再建設定により変わる場合がある。                                         |
| `r_max`                  | `7`    | 1 レイヤー内の最大カウンター段数。スロットは R0 から R(r_max) まで作られる。                           |
| `f_max`                  | `3`    | サイクル内の最大レイヤー数。L1 を含む。                                                                |
| `post_r_max_base_factor` | `1`    | 新レイヤー作成時の `layer_base_units = base_units * post_r_max_base_factor`。                          |
| `round_step_pips`        | `0.1`  | 間隔、TP、SL の pips 丸め単位。                                                                        |

### 3.2 カウンター間隔

| パラメータ          | 既定値     | 説明                                                                                                               |
| ------------------- | ---------- | ------------------------------------------------------------------------------------------------------------------ |
| `interval_mode`     | `constant` | `manual` なら `manual_intervals` を使う。`constant` 以外の自動モードは、現在の実装では同じガンマ減衰カーブを使う。 |
| `manual_intervals`  | `[]`       | `interval_mode=manual` 時の R1..R(r_max) の間隔。長さは `r_max` と一致する必要がある。                             |
| `n_pips_head`       | `30`       | 自動モードの開始間隔。                                                                                             |
| `n_pips_tail`       | `14`       | 減衰後の下限間隔。                                                                                                 |
| `n_pips_flat_steps` | `2`        | 減衰前に `n_pips_head` を使う段数。                                                                                |
| `n_pips_gamma`      | `1.4`      | 減衰カーブ係数。                                                                                                   |

`counter_interval_pips(k)` の `k` は 1-based で、R1 追加前の間隔が `k=1` である。`manual` は `manual_intervals[k - 1]` を使い、範囲外は最後の値に clamp する。`constant` は常に `n_pips_head` を返す。`additive` / `subtractive` / `multiplicative` / `divisive` は名前だけを保持しており、現在の実装では以下の共通カーブを使う。

```
if k <= n_pips_flat_steps:
    interval = n_pips_head
else:
    progress = (k - n_pips_flat_steps) / (r_max - n_pips_flat_steps)
    interval = max(n_pips_head - (n_pips_head - n_pips_tail) * progress^n_pips_gamma, n_pips_tail)
```

計算結果は `round_step_pips` の最近傍倍数へ `ROUND_HALF_UP` で丸める。

### 3.3 カウンターTP

| パラメータ               | 既定値         | 説明                                           |
| ------------------------ | -------------- | ---------------------------------------------- |
| `counter_tp_mode`        | `weighted_avg` | カウンターTPの計算方式。                       |
| `counter_tp_pips`        | `25`           | `fixed` または段階モードの基準 TP 幅。         |
| `counter_tp_step_amount` | `2.5`          | `additive` / `subtractive` の段ごとの増減量。  |
| `counter_tp_multiplier`  | `1.2`          | `multiplicative` / `divisive` の段ごとの倍率。 |

`weighted_avg` では同じレイヤー内のライブエントリーと `pending_rebuild` を含めた加重平均価格を TP にする。現在レイヤーに R0 がなく、動的ヘッドが別に存在する場合は、そのヘッドも参照に含める。

`counter_tp_mode` が `weighted_avg` 以外の場合、カウンター追加後に同じレイヤーの全ライブカウンターTPを再計算する。各モードの pips 幅は以下で、いずれも `round_step_pips` で丸める。

| モード           | pips 幅                                             |
| ---------------- | --------------------------------------------------- |
| `fixed`          | `counter_tp_pips`                                   |
| `additive`       | `counter_tp_pips + step_amount * (k - 1)`           |
| `subtractive`    | `max(counter_tp_pips - step_amount * (k - 1), 0.1)` |
| `multiplicative` | `counter_tp_pips * multiplier^(k - 1)`              |
| `divisive`       | `max(counter_tp_pips / multiplier^(k - 1), 0.1)`    |

### 3.4 ロスカット

| パラメータ                             | 既定値            | 説明                                                                                            |
| -------------------------------------- | ----------------- | ----------------------------------------------------------------------------------------------- |
| `stop_loss_enabled`                    | `false`           | 有効時、建玉時に SL を設定する。`shrink_enabled` とは併用不可。                                 |
| `stop_loss_mode`                       | `auto`            | `auto` は次のカウンター間隔と TP 幅から SL を配置する。その他のモードは建値からの絶対 pips 幅。 |
| `stop_loss_pips_*`                     | `n_pips_*` と同等 | `constant` / 減衰モードで使う SL 幅。                                                           |
| `stop_loss_manual_pips`                | `[]`              | `manual` 時の R0.. の SL 幅。少なくとも `r_max` 件必要。                                        |
| `preserve_highest_retracement_enabled` | `false`           | 各レイヤーの最上位ライブ R スロットを一時的に SL 対象外にする。                                 |
| `preserve_highest_r_from`              | `1`               | 最上位 R 保護を開始する R 番号。                                                                |

`preserve_highest_retracement_enabled=false` の場合、正規化済みパラメータから `preserve_highest_r_from` は除外され、内部値は `0` になる。

### 3.5 再建

| パラメータ                             | 既定値  | 説明                                                                                                 |
| -------------------------------------- | ------- | ---------------------------------------------------------------------------------------------------- |
| `refill_limit_enabled`                 | `true`  | 通常 TP 後に再利用できるカウンタースロットに上限を設定する。無効時は R1..R(r_max) が再利用可能。   |
| `refill_up_to`                         | `2`     | `refill_limit_enabled=true` 時、通常 TP 後に再利用できるカウンタースロット上限。                     |
| `rebuild_enabled`                      | `true`  | SL されたスロットを `pending_rebuild` として保持し、価格が戻ったら再建する。                         |
| `rebuild_entry_price_mode`             | `original_entry` | `original_entry` は元の建玉価格、`stop_loss_exit` はロスカット時の約定価格に戻ったときに再建する。 |
| `rebuild_stop_loss_mode`               | `same_pips` | 再建後も SL する場合、元の絶対 SL 価格、元の SL 幅、または手動 pips 幅を使うか。                 |
| `rebuild_stop_loss_manual_pips`        | `[]`    | `rebuild_stop_loss_mode=manual` 時の R0..R(r_max) の SL 幅。                                         |
| `rebuild_take_profit_mode`             | `same_pips` | 再建ポジションの TP。`same` は停止前の絶対 TP、`same_pips` は停止前の TP 幅を pips 距離として引き継ぐ。 |
| `rebuild_take_profit_pips_head`        | `25`    | 再建TP幅の開始値。                                                                                   |
| `rebuild_take_profit_pips_tail`        | `10`    | 再建TP幅の下限値。                                                                                   |
| `rebuild_take_profit_pips_flat_steps`  | `0`     | 再建TP幅の減衰前に開始値を維持するスロット数。                                                       |
| `rebuild_take_profit_pips_gamma`       | `1.4`   | 再建TP幅の減衰カーブ係数。                                                                           |
| `rebuild_take_profit_manual_pips`      | `[]`    | `rebuild_take_profit_mode=manual` 時の R0..R(r_max) の TP 幅。                                       |
| `reseed_on_all_pending`                | `false` | その方向の全サイクルが PENDING になったら新サイクルを作る。                                          |

### 3.6 証拠金保護と検証

| パラメータ                      | 既定値  | 説明                                                                                                 |
| ------------------------------- | ------- | ---------------------------------------------------------------------------------------------------- |
| `shrink_enabled`                | `false` | 証拠金比率が `m_th` 以上なら、損失の大きい建玉を前方から縮小する。`stop_loss_enabled` とは併用不可。 |
| `m_th`                          | `70`    | shrink 開始比率。                                                                                     |
| `m1_th`                         | `50`    | shrink の目標比率。                                                                                  |
| `emergency_enabled`             | `true`  | 証拠金比率が `emergency_threshold` 以上ならタスクをエラー停止する。                                  |
| `emergency_threshold`           | `95`    | emergency stop の比率。                                                                              |

### 3.7 正規化と検証

`SnowballStrategyConfig.from_dict()` は入力をゆるく parse し、欠落値は既定値で補完する。`strict_from_dict()` は永続化済み設定向けで、原則として `to_dict()` に含まれる全フィールドを要求する。ただし `preserve_highest_retracement_enabled=false` の場合の `preserve_highest_r_from` は省略を許容する。

主な検証条件は以下。

- `stop_loss_enabled` と `shrink_enabled` は同時に有効化できない。
- `rebuild_enabled=false` は `stop_loss_enabled=true` が必要。
- `preserve_highest_retracement_enabled=true` の場合、`1 <= preserve_highest_r_from <= r_max` が必要。無効時は内部値 `0`。
- shrink 有効時は `0 < m1_th < m_th < 100` が必要。
- emergency 有効時は `0 < emergency_threshold <= 100` が必要。
- `n_pips_head >= n_pips_tail > 0`、`n_pips_flat_steps < r_max` が必要。
- `interval_mode=manual` の `manual_intervals` は長さ `r_max`、各値 `>= 1` が必要。
- `refill_limit_enabled=true` の場合、`1 <= refill_up_to <= r_max` が必要。
- `stop_loss_pips_head >= stop_loss_pips_tail > 0`、`0 <= stop_loss_pips_flat_steps < r_max`、`stop_loss_pips_gamma > 0` が必要。
- `stop_loss_mode=manual` の `stop_loss_manual_pips` は少なくとも `r_max` 件、各値 `> 0` が必要。
- `rebuild_entry_price_mode` は `original_entry` / `stop_loss_exit` のみ。
- `rebuild_stop_loss_mode` は `same` / `same_pips` / `manual` のみ。`manual` では `rebuild_stop_loss_manual_pips` が少なくとも `r_max + 1` 件、各値 `> 0` が必要。
- `rebuild_take_profit_mode` は `same` / `same_pips` / `constant` / `additive` / `subtractive` / `multiplicative` / `divisive` / `manual` のみ。
- `rebuild_take_profit_*` は head >= tail > 0、flat steps < r_max、gamma > 0 が必要。
- `rebuild_take_profit_mode=manual` では `rebuild_take_profit_manual_pips` が少なくとも `r_max + 1` 件、各値 `> 0` が必要。
## 4. サイクルとグリッド

### 4.1 構造

各サイクルは `PositionGrid` を持つ。全ポジションはグリッド内のスロットに配置される。

```
Cycle
├── direction: LONG | SHORT
├── status: ACTIVE | PENDING | COMPLETED
└── grid: PositionGrid
    └── layers[]
        ├── Layer 1 (L1)
        │   ├── R0: 初期エントリー
        │   ├── R1: カウンター 1
        │   ├── R2: カウンター 2
        │   └── ... R(r_max)
        ├── Layer 2 (L2)
        │   ├── R0: レイヤー初期エントリー
        │   ├── R1: カウンター 1
        │   └── ...
        └── Layer 3 (L3) ...
```

実装では L/R 番号は 1-based のレイヤー番号と 0-based の R 番号で表現される。L1/R0 がサイクル最初の建玉である。

### 4.2 Entry の role と識別子

`Entry` はグリッド座標、価格、数量、ライフサイクル損益、イベント用メタデータを持つ。`role` は決済順序を直接変えないが、イベント表示とバスケット分類に使われる。

| role            | 説明                                                                 |
| --------------- | -------------------------------------------------------------------- |
| `initial`       | L1/R0 のサイクル初期エントリー。                                     |
| `counter`       | 各レイヤーの R1..R(r_max) に入る逆行側エントリー。                   |
| `layer_initial` | L2 以降の R0。前レイヤーが満杯または再利用不能になった後に作られる。 |

識別子は以下の意味を持つ。

- `entry_id`: Snowball state 内で採番される内部ID。
- `position_id`: broker / DB 側のポジションID。注文約定結果または再開時照合で反映される。
- `root_entry_id`: 同一サイクルまたは同一グループの起点ID。可視化の `visual_group_id` にも使う。
- `parent_entry_id`: 起点となった親エントリーID。
- `trade_cycle_id`: broker/DB 側の取引サイクルID。可視化の cycle key に使う。

### 4.3 実行状態

`SnowballStrategyState` は以下を永続化する。

- `protection_level`: `normal` / `shrink` / `emergency`。
- `initialised`: 初回ティックで初期サイクルを作成済みか。
- `cycles`: 全サイクル。`COMPLETED` も履歴として残る。
- `next_entry_id`: 次の内部エントリーID。
- 直近価格: `last_bid`、`last_ask`、`last_mid`。
- 口座値: `account_balance`、`account_nav`。
- `metrics`: 実行状況や UI 表示用の任意メトリクス。現在は `margin_ratio` を `ratio / 100` 形式の文字列で保存する。

永続化済み state は `state_parsing.py` で厳格に parse される。必須キー欠落、型不一致、ISO datetime でない時刻、数値変換不能な値は例外になる。

### 4.4 ヘッドとサイクルTP

`PositionGrid.head_entry()` は、グリッドを L1 から順に走査して最初に見つかるライブエントリーを返す。これは「動的ヘッド」として、カウンター追加時の含み損判定やヘッドIDの引き継ぎに使う。

ただし、現在のサイクル完了判定は動的ヘッドではなく L1/R0 固定である。`_process_cycle_tp()` は L1/R0 の `close_price` を見て、以下の条件でサイクルTPを処理する。

- L1/R0 がライブエントリーである。
- L1/R0 の TP がヒットしている。
- カウンターがない、または残っている全カウンターの TP も同一ティックでヒットしている。

L1/R0 が `pending_rebuild` の場合、TP 領域に到達してもクローズできないため、再建完了を待つ。

### 4.5 スロット状態

| 状態       | `entry` | `pending_rebuild`     | `ever_closed` | 説明                                                   |
| ---------- | ------- | --------------------- | ------------- | ------------------------------------------------------ |
| 空・未使用 | `None`  | `None`                | `false`       | 新規エントリー配置可能。                               |
| 使用中     | `Entry` | `None`                | 任意          | ライブエントリーを保持。                               |
| SL再建待ち | `None`  | `StopLossClosedEntry` | `false`       | SLで閉じた建玉のスナップショットを保持し、再建を待つ。 |
| 空・sealed | `None`  | `None`                | `true`        | 再利用不可。次の逆行では新レイヤーが必要になる。       |

判定プロパティ:

| プロパティ           | 条件                                                            | 用途                                             |
| -------------------- | --------------------------------------------------------------- | ------------------------------------------------ |
| `is_occupied`        | `entry is not None`                                             | ライブエントリー有無。                           |
| `is_present`         | `entry is not None OR pending_rebuild is not None`              | 論理的な存在判定。距離計算とレイヤー進行に使う。 |
| `is_pending_rebuild` | `pending_rebuild is not None`                                   | 再建待ち判定。                                   |
| `is_available`       | `entry is None AND not ever_closed AND pending_rebuild is None` | 新規配置可能か。                                 |

### 4.6 クローズ時の状態遷移

- 通常TPクローズ: `refill_limit_enabled=true` の場合はカウンターR番号が `refill_up_to` 以下なら空・未使用に戻る。`refill_limit_enabled=false` の場合は R1..R(r_max) が再利用可能。それ以外は sealed。
- R0 クローズ: R0 は自動 refill 対象ではない。L2 以降の R0 はレイヤー初期エントリーとして、クローズ後にレイヤー除去対象になる。
- SLクローズ: `rebuild_enabled=true` なら `pending_rebuild`、`rebuild_enabled=false` なら sealed。
- 再建完了: `complete_rebuild()` により `pending_rebuild` を消し、新しい `Entry` を設定する。
- refillable なスロットを再オープンした場合、より高い R 番号の sealed 状態は解除される。これにより、低い R の再利用後に上位 R へ再び進める。
- protection による `remove_entry()` は対象スロットを sealed にする。

### 4.7 サイクルステータス

| ステータス  | 説明                                                                                    |
| ----------- | --------------------------------------------------------------------------------------- |
| `ACTIVE`    | ライブエントリーがあり、通常処理対象。                                                  |
| `PENDING`   | ライブエントリーはないが `pending_rebuild` が残っている。再建されると `ACTIVE` に戻る。 |
| `COMPLETED` | ライブエントリーも `pending_rebuild` もない。                                           |

## 5. ティック処理順序

1. `bid` / `ask` / `mid` と口座メトリクスを更新する。
2. `emergency_enabled` かつ証拠金比率が `emergency_threshold` 以上ならタスクをエラー停止する。
3. `shrink_enabled` かつ証拠金比率が `m_th` 以上なら shrink を行う。shrink が走ったティックでは通常のサイクル処理へ進まない。
4. 未初期化なら LONG を作成し、ヘッジ有効なら SHORT も作成して終了する。
5. 各 active cycle を処理する。
   - 空グリッドかつ `pending_rebuild` ありなら PENDING にし、まず再建を試す。
     - 再建が発生せずグリッドが空のままで、かつ `reseed_on_all_pending=false` の場合は、
       PENDING のまま後続のカウンター処理へ進む。`pending_rebuild` ヘッド（R0 スナップショット）を
       基準に、価格がさらに逆行すればカウンター追加（refill）や新レイヤー作成を行い、
       建玉が入れば `ACTIVE` に戻る。これにより PENDING サイクルが逆行に対して凍結せず、
       averaging を継続する。
     - `reseed_on_all_pending=true` の場合は PENDING のまま当ティックの処理を終え、
       再シード（7.2）で新サイクル作成に委ねる。
   - カウンターTPを新しいスロットから順に処理する。
   - L1/R0 のサイクルTPを処理する。
   - SLヒットを一括で閉じる。
   - 再建を試す。
   - 同一ティックでカウンターTPがなかった場合だけ、カウンター追加を最大 `f_max * (r_max + 1)` 回まで繰り返す。
   - グリッド順序を検証し、ステータスを更新する。
6. 必要なら方向ごとに再シードする。

## 6. カウンターエントリー

### 6.1 追加条件

カウンター追加は以下を満たす場合だけ行う。

1. サイクルが `ACTIVE`。
2. 新規建玉が許可されている。
3. 動的ヘッド、または R0 の `pending_rebuild` が含み損状態。
4. 同一ティック内でカウンターTPクローズが発生していない。
5. 逆行距離が対象スロットの間隔以上。

含み損判定は LONG なら `bid`、SHORT なら `ask` を使う。

### 6.2 スロット選択

`next_available_counter_slot()` は R1 から順に走査する。

- `pending_rebuild` のスロットはスキップして、より高い R 番号を探す。
- sealed スロットに到達したら `None` を返す。
- 空きスロットがあっても、より高い R 番号に live または pending のスロットが残っている場合は `None` を返す。低い R を先に refill してグリッド順序を反転させないためである。
- `None` の場合、現在レイヤーが満杯または再利用不能とみなし、新レイヤー作成を検討する。

### 6.3 逆行距離

現在価格は建玉側価格を使う。

- LONG: 現在の `ask`
- SHORT: 現在の `bid`

基準価格は以下の順序で決まる。

- 追加先より低い R 番号に present スロットがある場合、その最も高い R の元建値。
- なければ同レイヤー R0 の元建値。
- それもなければ動的ヘッドの建値。

同一ティック内で複数スロットを連続作成する場合は、R0 から対象スロットまでの累積間隔で判定する。

### 6.4 ロットサイズ

カウンターの数量は以下。

```
units = (R番号 + 1) * layer_base_units
```

例: `base_units=1000`、L1 の場合:

| スロット | units |
| -------- | ----- |
| R1       | 2000  |
| R2       | 3000  |
| R3       | 4000  |

L2 以降は `layer_base_units = base_units * post_r_max_base_factor` を使う。

### 6.5 カウンターTP

カウンターTPは新しいスロットから順に処理する。

- 各レイヤーで最も高い occupied スロットを確認する。
- L1/R0 はカウンターTPでは閉じない。
- TP ヒット時は `close_reason="counter_tp"` で閉じる。
- L2 以降では、カウンターが閉じたあと R0 だけが残り、その R0 の TP もヒットしていれば `layer_initial_tp` として閉じる。
- L2 以降のレイヤーが空になったら削除する。

### 6.6 新レイヤー作成

現在レイヤーの `next_available_counter_slot()` が `None` の場合、次の条件を満たすと新レイヤーを作る。

1. `cycle.layer_count < f_max`。
2. 動的ヘッド、または R0 の `pending_rebuild` が含み損状態。
3. 直近の present スロットからさらに必要間隔だけ逆行している。

新レイヤー判定では、直近 present スロットが同一ティックで作られたばかりなら、同レイヤー R0 から直近 present スロットの次段までの累積間隔で判定する。そうでなければ、直近 present スロットの建値から `counter_interval_pips(highest.index + 1)` 以上逆行したかを見る。

新レイヤーの R0 は `role="layer_initial"` で、数量は `trend_lot_size * layer.base_units`。`layer.base_units` は `base_units * post_r_max_base_factor` である。

レイヤー初期TPは次の順序で決まる。

1. 前レイヤーの最上位 present スロットがライブなら、その `close_price`。
2. 前レイヤーの最上位 present スロットが `pending_rebuild` なら、その `close_price`。
3. 前レイヤーに present スロットがなければ、新規建値から `m_pips`。

新レイヤー作成前には、既存のライブエントリーとの建玉価格順序を壊さないか確認する。LONG では新規建値が既存ライブ建値を上回る場合、SHORT では下回る場合、そのレイヤー作成をスキップして後続ティックで再試行する。

## 7. サイクルTPと再シード

### 7.1 L1/R0 TP

L1/R0 がライブ状態で TP に到達した場合:

- カウンターがなければ L1/R0 を閉じる。
- カウンターが残っている場合、全カウンターの TP も同一ティックで到達していれば、カウンターをまとめて閉じた後に L1/R0 を閉じる。
- どれかのカウンターTPが未到達なら、そのティックでは L1/R0 を閉じない。

L1/R0 を閉じた後、同じ方向に他の ACTIVE サイクルがなければ、新サイクルを作成する。すでに他の ACTIVE サイクルがある場合は作成しない。

### 7.2 PENDING 中の挙動と再シード

全ライブエントリーが SL で消え、`pending_rebuild` だけが残るとサイクルは PENDING になる。

PENDING サイクルの逆行時の扱いは `reseed_on_all_pending` で変わる。

- `reseed_on_all_pending=false`（既定）: PENDING サイクルは `pending_rebuild` ヘッドを基準に
  averaging を継続する。価格が逆行すれば、refill 可能なカウンタースロットを再エントリーし、
  refill 不可（sealed）なら次レイヤーの R0 を作成する。建玉が入ればサイクルは `ACTIVE` に戻る。
  これにより、ヘッドの再建価格に戻らない限り何も建てずに凍結する旧挙動を避ける。
- `reseed_on_all_pending=true`: PENDING サイクルは追加建玉を行わず、再シードに委ねる。

#### ヘッド解決（多層 PENDING 時）

ライブ建玉が 1 本も無い PENDING サイクルでは、ヘッド（逆行距離・含み損判定の基準）を
**グリッド全体で最も古い（最低 grid-key の）`pending_rebuild`** にフォールバックする。
ヘッドは最下位レイヤーに存在し、必ずしも現在（最上位）レイヤーの R0 ではないため、
最上位レイヤーの R0 だけを見ると多層 PENDING で解決に失敗し、サイクルが凍結する。
`effective_head()` と counter-add の head context は、いずれもこの全グリッド探索を使う。

#### ゴースト空レイヤーの除去

非 L1 のレイヤー初期（R0）がヘッドとして TP クローズされた際、そのレイヤーに
present 建玉（live もしくは `pending_rebuild`）が残らない場合は、そのレイヤーを除去する。
除去しないと、R0 が sealed（pending ではない）の空レイヤーが最上位レイヤーとして残り、
ヘッド解決を壊して PENDING サイクルを凍結させる。L1 は常に温存する。

PENDING サイクルがあるだけでは新サイクルは作成されない。新サイクルを作る条件は以下。

- その方向に active cycle が 1 つもない。
- または `reseed_on_all_pending=true` で、その方向の全サイクルが PENDING。

## 8. ロスカットと再建

### 8.1 SL価格

`stop_loss_enabled=false` の場合、SL価格は設定しない。

`stop_loss_mode=auto` の場合:

1. `tp_pips = abs(close_price - entry_price) / pip_size`
2. `next_interval = counter_interval_pips(slot_number)`
3. LONG は `next_entry_price = entry_price - next_interval * pip_size`
4. SHORT は `next_entry_price = entry_price + next_interval * pip_size`
5. R0、または `tp_pips < next_interval` の場合、SL は `next_entry_price`
6. それ以外の場合、SL はさらに `next_interval` だけ不利方向へ置く

R0 は `tp_pips` に関係なく、常に次のエントリー位置に SL を置く。

`stop_loss_mode` が `constant` / 減衰 / `manual` の場合は、`stop_loss_pips(slot_number)` を建値からの絶対距離として使う。

### 8.2 SLクローズ

各ティックで全ライブエントリーの SL を確認し、ヒットしたものを一括で閉じる。

以下は SL 対象外。

- SL価格がないエントリー。
- `preserve_highest_retracement_enabled=true` の条件を満たす、各レイヤーの最上位 live R スロット。

SLクローズ時:

1. `ClosePositionEvent` を `close_reason="stop_loss"` で発行する。
2. `rebuild_enabled=true` なら `StopLossClosedEntry` を作り、スロットを `pending_rebuild` にする。
3. `rebuild_enabled=false` ならスロットを sealed にする。

### 8.3 再建発動

再建は `stop_loss_enabled=true` かつ `rebuild_enabled=true` の場合だけ行う。

再建発動価格は `rebuild_entry_price_mode` で決まる。`original_entry` は停止前の `pending_rebuild.entry_price`、`stop_loss_exit` はロスカット時の `pending_rebuild.stop_loss_exit_price` を使う。SL で閉じた同一 tick では即時再建せず、次 tick 以降に発動判定する。

| 方向  | 基本条件               |
| ----- | ---------------------- |
| LONG  | `bid >= trigger_price` |
| SHORT | `ask <= trigger_price` |

発動価格は、グリッド順序を壊さない範囲に clamp される。

### 8.4 再建エントリー

再建時は新しい `Entry` を作るが、以下を引き継ぐ。

- 方向
- units
- role
- layer / R番号
- root / parent entry id
- ライフサイクル損益と SL 回数

`Entry.open()` は現在ティックの建玉価格で作成するが、その後 `entry.entry_price` は再建発動価格に上書きされる。

再建TPは以下で決まる。

- `rebuild_take_profit_mode=same`: 停止前の絶対 TP 価格を使う。
- `rebuild_take_profit_mode=same_pips`: 停止前の建値から TP までの pips 距離を、再建建値から再適用する。
- その他のモード: 再建建値から `rebuild_take_profit_pips()` で計算する。
- グリッド順序を壊す場合は TP を clamp し、必要に応じて他の pending rebuild TP にも伝播する。

再建後の SL は以下。

- `rebuild_stop_loss_mode=same`: 停止前の絶対 SL 価格を再利用する。
- `rebuild_stop_loss_mode=same_pips`: 停止前の建値から SL までの pips 距離を、再建建値から再適用する。
- `rebuild_stop_loss_mode=manual`: `rebuild_stop_loss_manual_pips` を再建建値からの絶対距離として使う。

### 8.5 ライフサイクル損益

`Entry` は `lifecycle_realized_pnl` と `lifecycle_stop_loss_count` を持つ。SLクローズ時の損益と回数は `StopLossClosedEntry` に引き継がれ、再建後の `Entry` に戻される。通常TP、カウンターTP、レイヤー初期TP、shrink では、`close_entry()` が対象エントリーとサイクルの実現損益を加算する。

SL以外のクローズで単発損益がマイナスになった場合、またはSLを含むスロットライフサイクルの最終損益がマイナスのまま閉じた場合は warning を出す。サイクルが `COMPLETED` になった時点で `cycle.realized_pnl < 0` の場合も warning を出す。

## 9. 証拠金保護

### 9.1 Emergency

`emergency_enabled=true` かつ証拠金比率が `emergency_threshold` 以上なら、`protection_level=emergency` にして `STRATEGY_STOPPED` イベントを出し、タスクをエラー停止する。イベントの `data.kind` は `emergency_stop`、`validation_status` は `fail`。

### 9.2 Shrink

`shrink_enabled=true` かつ証拠金比率が `m_th` 以上なら SHRINK に入る。`m1_th` 未満になるまで、各 active cycle の前方候補から、最も含み損 pips が大きい建玉を閉じる。

前方候補は `grid.front_entry()` で決まる。基本は低いレイヤー、低い R 番号からだが、上位レイヤーに複数建玉が残る場合は、下位レイヤーの最後の 1 本を温存する。

各 shrink クローズは `close_reason="shrink"`、`validation_status="warn"`、`margin_ratio=ratio / 100` を持つ。クローズ後は対象エントリーをグリッドから除去し、証拠金比率を再計算する。

閉じる対象がなく、証拠金比率がまだ `m1_th` 以上の場合は、close order violation としてタスクをエラー停止する。shrink の結果、active cycle のグリッドが空になった場合は残っている `pending_rebuild` を消し、サイクルを `COMPLETED` にする。

## 10. グリッド順序と再開互換性

### 10.1 グリッド順序

各ティック末尾でグリッドの建玉価格と TP の順序を検証する。対象は live entry と `pending_rebuild` の両方である。違反がある場合はログに残し、順序が回復するまで新規カウンター追加を止めるが、タスクは失敗させない。

期待順序は以下。

| 方向  | 建玉価格順序 | TP順序 |
| ----- | ------------ | ------ |
| LONG  | 降順         | 降順   |
| SHORT | 昇順         | 昇順   |

`rebuild_take_profit_mode=manual` の場合は、手動TPが意図的に順序を崩す可能性があるため、検証では TP 順序を確認しない。

新レイヤー初期エントリーを作る前にも、既存レイヤーとの建玉価格順序を壊す場合は、そのレイヤー作成をスキップする。

再建時は、先行する live entry の建玉価格を hard bound として再建発動価格を clamp する。TP も先行する live entry の TP を hard bound として clamp し、先行する `pending_rebuild` の TP は必要に応じて新しい TP まで伝播させる。これにより、再建順序が前後してもグリッドの単調性を維持する。

### 10.2 再開互換性

タスク再開時、現在の `r_max` が以前の `r_max` より小さい場合は再開できない。グリッドのスロット数を減らす変更は、既存状態との互換性を壊すためである。

## 11. 約定反映と再開照合

### 11.1 注文約定結果の反映

`apply_event_execution_result()` は broker / executor から返った `entry_binding` を state に反映する。

- `entry_id` と `position_id` がある場合、該当する live entry に `position_id` を保存する。
- `fill_price` がある場合、`sync_entry_fill_price()` で建玉価格を実約定価格に合わせる。
- fill price の差分は `entry_price` に反映され、SL があれば同じ差分だけ移動する。
- `counter_tp_mode=weighted_avg` のカウンターでは、同じレイヤーの加重平均TPを再計算する。
- それ以外の entry では `close_price` を fill price 差分だけ移動する。
- `binding.cycle_id` があり、対象 cycle の `cycle_id` が `entry_id` と一致し、`trade_cycle_id` が未設定なら `trade_cycle_id` に保存する。

### 11.2 Broker ポジション照合

Snowball は `supports_stateful_broker_reconciliation()` が `true` で、タスク再開時に broker / DB 側の open positions と永続化 state を照合できる。

照合順序は以下。

1. `entry.position_id` があれば、同じ ID の open position を探す。
2. ID で見つからなければ、未割当の open position から `layer_index`、`retracement_count`、`direction`、`units` が一致するものを探す。
3. 1 件だけ見つかれば relink し、entry に position 情報を反映する。
4. 複数候補があれば blocker にして、誤った relink を避ける。
5. 見つからなければ blocker にして、外部決済された可能性を報告する。
6. state 側に割当できない open position が残れば blocker にして、合成未対応の open entry として報告する。

照合で position を entry に適用するときは、`position_id`、`direction`、絶対数量、fill price、`layer_number`、`retracement_count`、`opened_at` を更新する。fill price の更新規則は注文約定結果の反映と同じである。最後に `account_balance` を `state.current_balance` に合わせ、`account_nav = account_balance + sum(open_position.unrealized_pnl)` に更新する。

## 12. イベントと可視化

### 12.1 イベントメタデータ

Open / Rebuild / Close の各イベントには `events.py` で Snowball 固有メタデータを付ける。

| フィールド               | 内容                                             |
| ------------------------ | ------------------------------------------------ |
| `strategy_type`          | `snowball`                                       |
| `basket`                 | entry の `role`                                  |
| `root_entry_id`          | 起点 entry ID                                    |
| `parent_entry_id`        | 親 entry ID                                      |
| `visual_group_id`        | `root_entry_id` の文字列                         |
| `step`                   | entry の step                                    |
| `close_reason`           | TP、SL、保護などの理由                           |
| `validation_status`      | `pass` / `warn` / `fail` / `not_applicable` など |
| `expected_interval_pips` | 期待された逆行間隔                               |
| `actual_interval_pips`   | 実際の逆行距離                                   |
| `expected_tp_pips`       | 期待されたTP幅                                   |
| `actual_tp_pips`         | 実際の決済 pips                                  |
| `expected_exit_price`    | planned `close_price`                            |
| `actual_exit_price`      | tick の決済側価格                                |

主な `close_reason` は以下。

| close_reason            | 意味                    |
| ----------------------- | ----------------------- |
| `tp`                    | L1/R0 のサイクルTP。    |
| `counter_tp`            | カウンターTP。          |
| `layer_initial_tp`      | L2以降の R0 TP。        |
| `stop_loss`             | SL保護による決済。      |
| `shrink`                | Shrink 保護による決済。 |

### 12.2 Strategy capabilities

レジストリ上の Snowball は以下の capability を返す。

- runtime: `hedging=true`。
- visualization: `kind=cycle_grid`、`cycle_statuses=true`、`grid=true`。
- events: close reason labels と strategy event labels。
- resume: `stateful_broker_reconciliation=true`。

### 12.3 可視化用グリッド状態

`build_cycle_grid_state_map()` は `cycle_id` または `trade_cycle_id` をキーに、各サイクルのレイヤー/スロット状態を返す。`build_cycle_status_map()` は `trade_cycle_id` をキーに cycle status を返す。

スロット可視化状態は以下。

| state     | 条件                                            |
| --------- | ----------------------------------------------- |
| `filled`  | `slot.entry` があり、`entry.is_rebuild=false`。 |
| `rebuilt` | `slot.entry` があり、`entry.is_rebuild=true`。  |
| `stopped` | `slot.pending_rebuild` がある。                 |
| `empty`   | live entry も pending rebuild もない。          |

summary には `filled` / `stopped` / `rebuilt` / `empty` 件数、`layer_count`、`slot_count_per_layer` が入る。

## 13. レジストリ、スキーマ、パラメータAPI

Snowball は `id="snowball"`、schema `trading/schemas/snowball.json`、display name `Snowball Strategy` として登録される。schema は UI 向けに `title_ja`、`description_ja`、`enum_labels_ja`、`group_ja`、`dependsOn`、`linkedCount` を持つ。

`default_parameters()` は `SnowballStrategyConfig.from_dict({})` を `to_dict()` へ変換し、`preserve_highest_retracement_enabled=false` のときは `preserve_highest_r_from` を落とす。`normalize_parameters()` も同じ正規化を行う。`validate_parameters()` はまず基底 `Strategy.validate_parameters()` で JSON schema を確認し、その後 Snowball 固有の組み合わせ検証を行う。

`pip_size` は config dataclass に存在するが、実行時の `SnowballStrategy` にはタスク/銘柄側から別途 `pip_size` が渡る。schema の主要パラメータ一覧には `pip_size` は含まれない。

## 14. 手動テスト

### 14.1 実行

```bash
cd backend
uv run python -m tests.manual.test_snowball_visual
```

特定シナリオだけ実行:

```bash
uv run python -m tests.manual.test_snowball_visual 3
uv run python -m tests.manual.test_snowball_visual 5
```

### 14.2 シナリオ

| #   | シナリオ           | 検証内容                                                    |
| --- | ------------------ | ----------------------------------------------------------- |
| 1   | 順行               | 初期エントリー、L1/R0 TP、新サイクル作成。                  |
| 2   | 逆行               | R1、R2、R3... が設定間隔で追加される。                      |
| 3   | SLと再建           | SLクローズ、`pending_rebuild`、価格戻り、再建。             |
| 4   | 二重反転           | カウンター、TP、再逆行、SL、再建、TP。                      |
| 5   | SLスロットブロック | `pending_rebuild` スロットを再利用せず、次の R 番号に進む。 |

### 14.3 自動テストの参照先

実装仕様の主要な確認先は以下。

| ファイル                                                                        | 主な対象                                         |
| ------------------------------------------------------------------------------- | ------------------------------------------------ |
| `backend/tests/unit/trading/strategies/snowball/test_calculators.py`            | 間隔、TP、SL幅、再建TP幅、丸め。                 |
| `backend/tests/unit/trading/strategies/snowball/test_models.py`                 | Entry、Slot、Layer、PositionGrid、Cycle、State。 |
| `backend/tests/unit/trading/strategies/snowball/test_grid_policy.py`            | グリッド順序、TP境界、pending TP 伝播。          |
| `backend/tests/unit/trading/strategies/snowball/test_strategy.py`               | 初期化、サイクルTP、SL保護、再建、broker 照合。  |
| `backend/tests/unit/trading/strategies/snowball/test_snowball_tick_patterns.py` | ティック列、カウンター、SL、再シード、再建順序。 |
| `backend/tests/integration/trading/test_snowball_backtest_simulation.py`        | BacktestExecutor 経由のシミュレーション、再開。  |
| `backend/tests/integration/trading/test_snowball_integration.py`                | レジストリ、設定モデル、serializer 統合。        |
| `backend/tests/e2e/trading/test_snowball_configs_api.py`                        | API 経由の strategy/config CRUD と検証。         |
