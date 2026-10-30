// -----------------------------------------------------------------------------
// mxfp4_uvm_pkg
//   付録A (UVM ベース検証仕様) の env 実装。9 章のプレーン SV 環境が既定で、
//   本パッケージはオプション (付録A A.1.1)。
//
//   リファレンスモデル関数群は mxfp4_ref_pkg を import してプレーン SV 版 TB と
//   共用する (A.6.1。二重メンテナンスの回避)。
//   SVA も tb/mxfp4_bdp_sva.sv の bind をそのまま共用する (A.3.4)。
//
//   実行は sukimasim の UVM モード。--enable-uvm が必須。
//     sukimasim --enable-uvm -top hw_top +UVM_TESTNAME=<test> ...
// -----------------------------------------------------------------------------
`timescale 1ns/1ps

package mxfp4_uvm_pkg;
  import uvm_pkg::*;
  `include "uvm_macros.svh"

  import mxfp4_pkg::*;
  import mxfp4_ref_pkg::*;

  `include "env_config.svh"
  `include "mxfp4_items.svh"
  `include "bdp_seq_lib.svh"
  `include "bdp_agent.svh"
  `include "mxfp4_scoreboard.svh"
  `include "mxfp4_cov.svh"
  `include "mxfp4_env.svh"
  `include "mxfp4_test_lib.svh"

  // quant_encoder レベル (enc env)。トップは hw_enc_top。
  `include "enc_seq_lib.svh"
  `include "enc_agent.svh"
  `include "enc_scoreboard.svh"
  `include "enc_env.svh"
  `include "enc_test_lib.svh"

  // mxfp4_fp32_add_core レベル (add_core env、R2f)。トップは hw_add_top。
  `include "addcore_seq_lib.svh"
  `include "addcore_agent.svh"
  `include "addcore_scoreboard.svh"
  `include "addcore_env.svh"
  `include "addcore_test_lib.svh"

  // mxfp4_gemm_top レベル (GEMM env、E3)。トップは hw_gemm_top。
  `include "gemm_seq_lib.svh"
  `include "gemm_agent.svh"
  `include "gemm_scoreboard.svh"
  `include "gemm_env.svh"
  `include "gemm_test_lib.svh"
endpackage
