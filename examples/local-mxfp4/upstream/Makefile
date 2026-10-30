# -----------------------------------------------------------------------------
# ブロックスケール MXFP4 演算器 — ビルド / 検証
#   docs/mxfp4_spec_rev1.0.md に対応する RTL とテストベンチを扱う。
#
#   make lint    : Verilator による RTL + SVA の静的検査
#   make test    : lint + 全テストベンチをビルドして実行
#   make sim-add / sim-bdp / sim-enc / sim-gemm / sim-top : 個別実行
#   make sim-sukima : sukimasim でクラスベース TB を実行 (covergroup 有効)
#   make clean   : 生成物の削除
#
#   ランダム試行回数は plusargs で調整できる:
#     make sim-add    N_ADD=300000
#     make sim-bdp    N_R1=100000 N_R2A=20000 N_R2E=200
#     make sim-enc    N_R3=20000
#     make sim-gemm   N_GEMM=500
#     make sim-top    N_SERIES=2000 N_ENC=500
#     make sim-flow   N_FLOW=1000
#     make sim-sukima N_SERIES=200 N_ENC=60
#
#   注: Icarus Verilog は for ループ内の break 文 (仕様書 5.6 節の LZC、
#       10 章で検証対象言語機能として明記) を未サポートのため使用しない。
# -----------------------------------------------------------------------------

BUILD := build
VERILATOR ?= verilator

RTL_CORE := \
	rtl/mxfp4_pkg.sv \
	rtl/e2m1_decode.sv \
	rtl/elem_mul.sv \
	rtl/scale_add.sv \
	rtl/reduce_tree.sv \
	rtl/mxfp4_i2f.sv \
	rtl/mxfp4_fp32_add_core.sv \
	rtl/mxfp4_lza.sv \
	rtl/mxfp4_fp32_add_nearfar.sv \
	rtl/mxfp4_bdp.sv

RTL_ENC := \
	rtl/mxfp4_pkg.sv \
	rtl/e2m1_quantize.sv \
	rtl/amax_tree32.sv \
	rtl/quant_encoder.sv

RTL_GEMM := \
	$(RTL_CORE) \
	rtl/gemm_ctrl_fsm.sv \
	rtl/mxfp4_gemm_top.sv

# ready 拡張 (仕様書 3.3 節) の入力 FIFO 付きラッパ
RTL_FLOW := \
	$(RTL_CORE) \
	rtl/mxfp4_fifo.sv \
	rtl/mxfp4_bdp_fifo.sv

# クラスベース TB (仕様書 9.1 節) が使う RTL 一式
RTL_TOP := \
	$(RTL_CORE) \
	rtl/e2m1_quantize.sv \
	rtl/amax_tree32.sv \
	rtl/quant_encoder.sv

REF := tb/mxfp4_ref_pkg.sv
SVA := tb/mxfp4_bdp_sva.sv

SUKIMASIM ?= /home/bamba/Work2/sukimasim/build/sukimasim

# 抑制する警告と理由
#   DECLFILENAME    : 1 ファイルに複数モジュールを置かない方針だが package 名は例外
#   PINCONNECTEMPTY : 未使用出力の空接続 (is_zero_o / sop4_dbg 等) は意図的
#   UNUSEDPARAM     : mxfp4_pkg の共通 localparam は一部モジュールでのみ使う
#   UNUSEDSIGNAL    : norm[27] / sig[23] / first_q[5] など構造上使わないビット
#   TIMESCALEMOD    : timescale は TB 側 (と --timescale) で一元指定する
#   SYNCASYNCNET    : SVA の disable iff (!rst_n) を同期使用と誤判定するため
#
# PROCASSINIT は絶対に抑制しないこと。宣言時初期値を持つ変数をプロセスから
# 駆動すると駆動が反映されず、DUT に 0 が入り続ける実バグを踏む。
VWARN := \
	-Wno-DECLFILENAME \
	-Wno-PINCONNECTEMPTY \
	-Wno-UNUSEDPARAM \
	-Wno-UNUSEDSIGNAL \
	-Wno-TIMESCALEMOD \
	-Wno-SYNCASYNCNET

VFLAGS := --timing --assert --timescale 1ns/1ps -j 4 -Wall $(VWARN)

# TB のサイズキャスト由来の幅警告は検証対象ではないので緩める
VFLAGS_TB := $(VFLAGS) -Wno-WIDTHTRUNC -Wno-WIDTHEXPAND

.PHONY: all lint test sim-add sim-bdp sim-enc sim-gemm sim-top sim-flow sim-q34 sim-guf sim-nf sim-bdp-nf sim-sukima sim-sukima-flow sim-uvm sim-uvm-enc sim-uvm-add sim-uvm-gemm repro clean

all: test

# -----------------------------------------------------------------------------
# 静的検査 (RTL + bind される SVA)
# -----------------------------------------------------------------------------
lint:
	$(VERILATOR) --lint-only -Wall --assert $(VWARN) +define+MXFP4_ASSERT \
		--top-module mxfp4_gemm_top $(RTL_GEMM) $(SVA)
	$(VERILATOR) --lint-only -Wall $(VWARN) \
		--top-module quant_encoder $(RTL_ENC)
	$(VERILATOR) --lint-only -Wall $(VWARN) -GUNBIASED_34=1 \
		--top-module quant_encoder $(RTL_ENC)
	$(VERILATOR) --lint-only -Wall --assert $(VWARN) +define+MXFP4_ASSERT \
		--top-module mxfp4_bdp_fifo $(RTL_FLOW) $(SVA)
	$(VERILATOR) --lint-only -Wall --assert $(VWARN) +define+MXFP4_ASSERT -GGRADUAL_UF=1 \
		--top-module mxfp4_bdp $(RTL_CORE) $(SVA)
	$(VERILATOR) --lint-only -Wall $(VWARN) \
		--top-module mxfp4_fp32_add_nearfar \
		rtl/mxfp4_pkg.sv rtl/mxfp4_lza.sv rtl/mxfp4_fp32_add_nearfar.sv
	$(VERILATOR) --lint-only -Wall $(VWARN) -GGRADUAL_UF=1 \
		--top-module mxfp4_fp32_add_nearfar \
		rtl/mxfp4_pkg.sv rtl/mxfp4_lza.sv rtl/mxfp4_fp32_add_nearfar.sv
	@echo "lint: OK"

# -----------------------------------------------------------------------------
# テストベンチ
# -----------------------------------------------------------------------------
# 加算器単体。BDP 経由では第 2 項が i2f 由来の 13bit 仮数に限られ、桁上げ時の
# sticky が丸めに効く条件を踏めないため、汎用 FP32 加算器として別に検証する。
$(BUILD)/tb_add: rtl/mxfp4_pkg.sv rtl/mxfp4_fp32_add_core.sv $(REF) tb/tb_fp32_add.sv
	@mkdir -p $(BUILD)
	$(VERILATOR) --binary $(VFLAGS_TB) --top-module tb_fp32_add \
		--Mdir $(BUILD)/obj_add -o ../tb_add \
		rtl/mxfp4_pkg.sv rtl/mxfp4_fp32_add_core.sv $(REF) tb/tb_fp32_add.sv

$(BUILD)/tb_bdp: $(RTL_CORE) $(SVA) $(REF) tb/tb_mxfp4_bdp.sv
	@mkdir -p $(BUILD)
	$(VERILATOR) --binary $(VFLAGS_TB) --top-module tb_mxfp4_bdp \
		--Mdir $(BUILD)/obj_bdp -o ../tb_bdp \
		$(RTL_CORE) $(SVA) $(REF) tb/tb_mxfp4_bdp.sv

$(BUILD)/tb_enc: $(RTL_ENC) $(REF) tb/tb_quant_encoder.sv
	@mkdir -p $(BUILD)
	$(VERILATOR) --binary $(VFLAGS_TB) --top-module tb_quant_encoder \
		--Mdir $(BUILD)/obj_enc -o ../tb_enc \
		$(RTL_ENC) $(REF) tb/tb_quant_encoder.sv

$(BUILD)/tb_gemm: $(RTL_GEMM) $(SVA) $(REF) tb/tb_mxfp4_gemm_top.sv
	@mkdir -p $(BUILD)
	$(VERILATOR) --binary $(VFLAGS_TB) --top-module tb_mxfp4_gemm_top \
		--Mdir $(BUILD)/obj_gemm -o ../tb_gemm \
		$(RTL_GEMM) $(SVA) $(REF) tb/tb_mxfp4_gemm_top.sv

# Packed rand lanes avoid the generated temporary; keep UNDRIVEN checks enabled.
$(BUILD)/tb_top: $(RTL_TOP) $(SVA) $(REF) tb/tb_top.sv
	@mkdir -p $(BUILD)
	$(VERILATOR) --binary $(VFLAGS_TB) --top-module tb_top \
		--Mdir $(BUILD)/obj_top -o ../tb_top \
		$(RTL_TOP) $(SVA) $(REF) tb/tb_top.sv

# 3/4 スケーリング (仕様書 7.7 節)。Algorithm 1 版と並走させて比較する。
$(BUILD)/tb_q34: $(RTL_ENC) $(REF) tb/tb_quant_q34.sv
	@mkdir -p $(BUILD)
	$(VERILATOR) --binary $(VFLAGS_TB) --top-module tb_quant_q34 \
		--Mdir $(BUILD)/obj_q34 -o ../tb_q34 \
		$(RTL_ENC) $(REF) tb/tb_quant_q34.sv

$(BUILD)/tb_bdp_nf: $(RTL_CORE) $(SVA) $(REF) tb/tb_mxfp4_bdp.sv
	@mkdir -p $(BUILD)
	$(VERILATOR) --binary $(VFLAGS_TB) -GUSE_NEARFAR=1 --top-module tb_mxfp4_bdp \
		--Mdir $(BUILD)/obj_bdp_nf -o ../tb_bdp_nf \
		$(RTL_CORE) $(SVA) $(REF) tb/tb_mxfp4_bdp.sv

# near/far 二経路 + LZA (仕様書 5.7 節 発展課題)。統合パス版とビット一致を見る。
$(BUILD)/tb_nf: rtl/mxfp4_pkg.sv rtl/mxfp4_fp32_add_core.sv rtl/mxfp4_lza.sv \
                rtl/mxfp4_fp32_add_nearfar.sv $(REF) tb/tb_nearfar.sv
	@mkdir -p $(BUILD)
	$(VERILATOR) --binary $(VFLAGS_TB) --top-module tb_nearfar \
		--Mdir $(BUILD)/obj_nf -o ../tb_nf \
		rtl/mxfp4_pkg.sv rtl/mxfp4_fp32_add_core.sv rtl/mxfp4_lza.sv \
		rtl/mxfp4_fp32_add_nearfar.sv $(REF) tb/tb_nearfar.sv

# gradual underflow (仕様書 6.3 節 発展課題)。FTZ 版と並走させて比較する。
$(BUILD)/tb_guf: $(RTL_CORE) $(SVA) $(REF) tb/tb_gradual_uf.sv
	@mkdir -p $(BUILD)
	$(VERILATOR) --binary $(VFLAGS_TB) --top-module tb_gradual_uf \
		--Mdir $(BUILD)/obj_guf -o ../tb_guf \
		$(RTL_CORE) $(SVA) $(REF) tb/tb_gradual_uf.sv

# ready 拡張 + FIFO のフロー制御 (仕様書 3.3 節)。FIFO 内の SVA を有効にするため
# MXFP4_ASSERT を定義する。
$(BUILD)/tb_flow: $(RTL_FLOW) $(SVA) $(REF) tb/tb_bdp_flow.sv
	@mkdir -p $(BUILD)
	$(VERILATOR) --binary $(VFLAGS_TB) +define+MXFP4_ASSERT --top-module tb_bdp_flow \
		--Mdir $(BUILD)/obj_flow -o ../tb_flow \
		$(RTL_FLOW) $(SVA) $(REF) tb/tb_bdp_flow.sv

sim-add: $(BUILD)/tb_add
	$(BUILD)/tb_add $(if $(N_ADD),+N_ADD=$(N_ADD))

sim-bdp: $(BUILD)/tb_bdp
	$(BUILD)/tb_bdp $(if $(N_R1),+N_R1=$(N_R1)) $(if $(N_R2A),+N_R2A=$(N_R2A)) $(if $(N_R2E),+N_R2E=$(N_R2E))

sim-enc: $(BUILD)/tb_enc
	$(BUILD)/tb_enc $(if $(N_R3),+N_R3=$(N_R3))

sim-gemm: $(BUILD)/tb_gemm
	$(BUILD)/tb_gemm $(if $(N_GEMM),+N_GEMM=$(N_GEMM))

sim-top: $(BUILD)/tb_top
	$(BUILD)/tb_top $(if $(N_SERIES),+N_SERIES=$(N_SERIES)) $(if $(N_ENC),+N_ENC=$(N_ENC))

sim-flow: $(BUILD)/tb_flow
	$(BUILD)/tb_flow $(if $(N_FLOW),+N_FLOW=$(N_FLOW))

sim-q34: $(BUILD)/tb_q34
	$(BUILD)/tb_q34 $(if $(N_Q34),+N_Q34=$(N_Q34))

sim-guf: $(BUILD)/tb_guf
	$(BUILD)/tb_guf $(if $(N_GUF),+N_GUF=$(N_GUF))

sim-nf: $(BUILD)/tb_nf
	$(BUILD)/tb_nf $(if $(N_NF),+N_NF=$(N_NF))

# BDP 全体を near/far 版の加算器で組み直し、同じリファレンスで回帰する
# (仕様書 12 章 注意 7 のビット一致回帰を BDP レベルでも掛ける)
sim-bdp-nf: $(BUILD)/tb_bdp_nf
	$(BUILD)/tb_bdp_nf $(if $(N_R1),+N_R1=$(N_R1)) $(if $(N_R2A),+N_R2A=$(N_R2A)) $(if $(N_R2E),+N_R2E=$(N_R2E))

# -----------------------------------------------------------------------------
# sukimasim (4-state / covergroup / SVA)
#   Verilator は covergroup 未対応なので機能カバレッジはこちらで取る。
#   4-state なので X 伝播の検査も兼ねる。Verilator より 4 桁ほど遅い。
# -----------------------------------------------------------------------------
sim-sukima:
	$(SUKIMASIM) -assert +define+MXFP4_COVERAGE -top tb_top --wall-timeout 1800 \
		$(RTL_TOP) $(SVA) $(REF) tb/tb_top.sv \
		$(if $(N_SERIES),+N_SERIES=$(N_SERIES)) $(if $(N_ENC),+N_ENC=$(N_ENC))

# ready 拡張のフロー制御を 4-state で回す。SVA のクロッキングイベント修飾
# (@(posedge clk iff in_ready)。IEEE 1800-2023 §9.4.2.3) の実行も兼ねる。
sim-sukima-flow:
	$(SUKIMASIM) -assert +define+MXFP4_ASSERT -top tb_bdp_flow --wall-timeout 1800 \
		$(RTL_FLOW) $(SVA) $(REF) tb/tb_bdp_flow.sv \
		$(if $(N_FLOW),+N_FLOW=$(N_FLOW))

# -----------------------------------------------------------------------------
# 付録A UVM ベース検証環境 (オプション。9 章のプレーン SV が既定)
#   sukimasim 専用。--enable-uvm が必須 (付けないと `uvm_info 等が未解決になる)。
#   テストは +UVM_TESTNAME で選ぶ。既定は D4 (mxfp4_bdp_acc_test)。
#     make sim-uvm UVM_TEST=mxfp4_r2a_test N_ITEM=50
#   BDP レベルのレグレッション (カバレッジ閉包つき) は
#     make sim-uvm UVM_TEST=mxfp4_bdp_regress_test
# -----------------------------------------------------------------------------
UVM_SRC := \
	tb/uvm/mxfp4_uvm_if.sv \
	tb/uvm/mxfp4_uvm_pkg.sv \
	tb/uvm/hw_clkgen.sv \
	tb/uvm/hw_top.sv

# GEMM env (mxfp4_gemm_top レベル)。トップは hw_gemm_top。
UVM_GEMM_SRC := \
	tb/uvm/mxfp4_uvm_if.sv \
	tb/uvm/mxfp4_uvm_pkg.sv \
	tb/uvm/hw_clkgen.sv \
	tb/uvm/hw_gemm_top.sv

# add_core env (mxfp4_fp32_add_core レベル)。トップは hw_add_top。
UVM_ADD_SRC := \
	tb/uvm/mxfp4_uvm_if.sv \
	tb/uvm/mxfp4_uvm_pkg.sv \
	tb/uvm/hw_clkgen.sv \
	tb/uvm/hw_add_top.sv

RTL_ADD := rtl/mxfp4_pkg.sv rtl/mxfp4_fp32_add_core.sv

# enc env (quant_encoder レベル)。トップは hw_enc_top、DUT は 1 つだけ。
UVM_ENC_SRC := \
	tb/uvm/mxfp4_uvm_if.sv \
	tb/uvm/mxfp4_uvm_pkg.sv \
	tb/uvm/hw_clkgen.sv \
	tb/uvm/hw_enc_top.sv

UVM_TEST ?= mxfp4_bdp_acc_test
UVM_VERB ?= UVM_LOW
UVM_MAXT ?= 50us
# GEMM の組合せ整定予算 (既定 64 では 16 PE を整定しきれない)。実験用に上書き可。
GEMM_COMB_BUDGET ?= 4096

sim-uvm:
	$(SUKIMASIM) --enable-uvm -assert -top hw_top \
		+UVM_TESTNAME=$(UVM_TEST) +UVM_VERBOSITY=$(UVM_VERB) \
		--max-time $(UVM_MAXT) --wall-timeout 1800 +incdir+tb/uvm \
		$(RTL_CORE) $(SVA) $(REF) $(UVM_SRC) \
		$(if $(N_ITEM),+N_ITEM=$(N_ITEM))

# 付録A UVM env の GEMM レベル (E3、方式 Y)。
#   SUKIMASIM_COMB_CALL_BUDGET を上げること。GEMM は 16 PE ぶんの組合せがあり、
#   既定の 64 では組合せの整定が打ち切られて
#   「Combinational settle still truncated ... Results may be stale」が大量に出る。
#   **打ち切られても exit 0 で TEST PASSED になる**ので、設定を忘れると
#   「stale かもしれない値で緑」という状態に気付けない。
#   wall-timeout も他より長く取る。GEMM は 1 実行に CPU 1000 秒超かかるので
#   既定の 1800 秒では既定 N でも打ち切られる。
sim-uvm-gemm: export SUKIMASIM_COMB_CALL_BUDGET = $(GEMM_COMB_BUDGET)
sim-uvm-gemm:
	$(SUKIMASIM) --enable-uvm -top hw_gemm_top \
		+UVM_TESTNAME=$(UVM_TEST) +UVM_VERBOSITY=$(UVM_VERB) \
		--max-time $(UVM_MAXT) --wall-timeout 14400 +incdir+tb/uvm \
		$(RTL_GEMM) $(REF) $(UVM_GEMM_SRC) \
		$(if $(N_ITEM),+N_ITEM=$(N_ITEM))

# 付録A UVM env の加算器レベル (R2f)。DUT は組合せなので SVA の bind 先が無い。
sim-uvm-add:
	$(SUKIMASIM) --enable-uvm -top hw_add_top \
		+UVM_TESTNAME=$(UVM_TEST) +UVM_VERBOSITY=$(UVM_VERB) \
		--max-time $(UVM_MAXT) --wall-timeout 1800 +incdir+tb/uvm \
		$(RTL_ADD) $(REF) $(UVM_ADD_SRC) \
		$(if $(N_ITEM),+N_ITEM=$(N_ITEM))

# 付録A UVM env の quant_encoder レベル。BDP 用の SVA は bind 先が無いので付けない。
sim-uvm-enc:
	$(SUKIMASIM) --enable-uvm -top hw_enc_top \
		+UVM_TESTNAME=$(UVM_TEST) +UVM_VERBOSITY=$(UVM_VERB) \
		--max-time $(UVM_MAXT) --wall-timeout 1800 +incdir+tb/uvm \
		$(RTL_ENC) $(REF) $(UVM_ENC_SRC) \
		$(if $(N_ITEM),+N_ITEM=$(N_ITEM))

# -----------------------------------------------------------------------------
# sukimasim へ報告した不具合の再現ケース (自己チェック型)
#   Verilator を対照に取る。期待値は「Verilator と同じ結果」。
# -----------------------------------------------------------------------------
repro:
	-$(SUKIMASIM) -assert -top tb_past_expr_minimal repro/past_expr_minimal.sv
	-$(SUKIMASIM) -top tb_constraint_partselect repro/constraint_partselect_minimal.sv
	-$(SUKIMASIM) -top tb_class_prop_partsel repro/class_prop_partsel_minimal.sv
	-$(SUKIMASIM) -top tb_class_prop_this repro/class_prop_this_partsel_minimal.sv
	-$(SUKIMASIM) -top tb_clocking_event repro/clocking_event_minimal.sv
	-$(SUKIMASIM) -top tb_enc_uvm_mode $(RTL_ENC) repro/uvm_mode_encoder_x_minimal.sv
	-$(SUKIMASIM) --enable-uvm -top tb_enc_uvm_mode $(RTL_ENC) repro/uvm_mode_encoder_x_minimal.sv
	-$(SUKIMASIM) -top tb_genvar_partselect repro/uvm_mode_genvar_port_select_minimal.sv
	-$(SUKIMASIM) --enable-uvm -top tb_genvar_partselect repro/uvm_mode_genvar_port_select_minimal.sv
	-$(SUKIMASIM) --enable-uvm -top tb_uvm_objection_drop_teardown \
		repro/uvm_objection_drop_teardown_minimal.sv
	-$(SUKIMASIM) -top tb_func_local_clobber repro/func_local_name_clobber_minimal.sv
	-$(SUKIMASIM) -top tb_if_unpacked_port_name_clash \
		repro/if_unpacked_port_name_clash_minimal.sv
	-$(SUKIMASIM) -top tb_if_unpacked_port_name_clash +define+RENAMED \
		repro/if_unpacked_port_name_clash_minimal.sv
	-$(SUKIMASIM) -top tb_assign_partsel_lhs repro/assign_partsel_lhs_minimal.sv
	-$(SUKIMASIM) -top tb_constraint_dist repro/constraint_dist_ignored_minimal.sv
	-$(SUKIMASIM) -top tb_partsel_const_expr_base repro/partsel_const_expr_base_error_minimal.sv
	-$(SUKIMASIM) --enable-uvm -top tb_uvm_task_local --max-time 50us \
		+UVM_TESTNAME=chk_test repro/uvm_task_local_loop_write_lost_minimal.sv
	@# +UVM_TESTNAME の解決が factory registry を経由しない件。
	@# A / E は走って PASS、B / C / D は fatal で止まるのが正しい (詳細はファイル冒頭)。
	-$(SUKIMASIM) --enable-uvm -top tb_uvm_testname_factory_bypass --max-time 1us \
		+UVM_TESTNAME=reg_plain_test      repro/uvm_testname_factory_bypass_minimal.sv
	-$(SUKIMASIM) --enable-uvm -top tb_uvm_testname_factory_bypass --max-time 1us \
		+UVM_TESTNAME=unreg_plain_test    repro/uvm_testname_factory_bypass_minimal.sv
	-$(SUKIMASIM) --enable-uvm -top tb_uvm_testname_factory_bypass --max-time 1us \
		+UVM_TESTNAME=no_such_test_at_all repro/uvm_testname_factory_bypass_minimal.sv
	-$(SUKIMASIM) --enable-uvm -top tb_uvm_testname_factory_bypass --max-time 1us \
		+UVM_TESTNAME=unreg_abstract_test repro/uvm_testname_factory_bypass_minimal.sv
	-$(SUKIMASIM) --enable-uvm -top tb_uvm_testname_factory_bypass --max-time 1us \
		+UVM_TESTNAME=concrete_child_test repro/uvm_testname_factory_bypass_minimal.sv

test: lint sim-add sim-bdp sim-enc sim-gemm sim-top sim-flow sim-q34 sim-guf sim-nf sim-bdp-nf
	@echo "all tests done"

clean:
	rm -rf $(BUILD)
