# 優先順位付き割込みのclaim・completeを検証する

4要因・1通知先の教材用コントローラにAPBを接続します。単なる割込み保持に加え、優先順位、threshold、処理中状態、ソフトウェアのclaim／completeを照合します。

## 教材の仕様

番地は0x00 ENABLE、0x04 THRESHOLD、0x08 PENDING（RO）、0x0C IN_SERVICE（RO）、0x10 CLAIM/COMPLETE、0x20〜0x2Cの4個が各PRIORITYです。要因IDは1〜4、優先順位は0〜3で、0は選択しません。同順位なら小さいIDを優先します。

IRQは有効なpendingの最高優先順位がthresholdより**大きい**ときだけ立ちます。claimは0x10の読出し完了で行い、thresholdとは独立に最高の有効pending IDを返します。候補がなければ0です。claimした要因をpendingから除き、処理中にします。completeは0x10へのID書込みで、実際に処理中のIDだけを解除します。不正ID、RO書込み、未定義番地はエラー・無副作用です。

`level`構成は入力highを捕捉し、complete後もhighなら再度pendingになります。`edge`構成は立上りを捕捉し、処理中の新しいエッジは捨てる仕様です。completeと同じエッジの新イベントも更新前の処理中状態で判定し、claimと同じ要因のイベントはclaimに含めます。マスク中のpendingは保持します。

この方式の参考は[OpenTitanの説明](https://opentitan.org/book/hw/top_earlgrey/ip_autogen/rv_plic/doc/theory_of_operation.html)と[RISC-Vのclaim規則](https://docs.riscv.org/reference/plic/v1.0.0/plic-claims.html)です。独自の小さいレジスタマップとイベント方針を持ち、PLIC全規格の適合性は認定しません。

## 検査・実行

Pythonは集合と優先順位から期待値を作り、APB応答・IRQ・pending・処理中状態を毎サイクル照合します。levelはAPB待ち1、edgeは待ち2で、各12目標です。smokeは32操作、nightlyは250操作×3 seedに固定シナリオを加えます。

4変異は同順位の逆順選択、thresholdの等号誤り、処理中状態の設定漏れ、マスク中pendingの消失です。

```sh
python3 examples/local-priority-irq/run.py
python3 examples/local-priority-irq/run.py --profile nightly
python3 -m unittest discover -s examples/local-priority-irq/tests -v
```

[共通の準備・証跡・判定](../local-common/README.md)を使います。2構成のJUnitは14／18件、確認テストは5件です。CPUの例外受付や実際のネスト処理、任意のクロック境界は対象外です。
