`timescale 1ns/1ps
interface replay_control_if;
  bit start_replay = 0, sample_valid = 0, sva_enabled = 1;
  int cycle = 0;
endinterface
