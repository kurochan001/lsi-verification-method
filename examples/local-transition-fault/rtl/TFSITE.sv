// SPDX-License-Identifier: Apache-2.0 WITH LLVM-exception
// What a fault site is in the design: a buffer. Synthesis takes the cell of the same name from the
// library instead, and the simulations of the netlist use cells/tf_site.v, which adds the faults.
module TFSITE(input wire A, output wire Y);
    assign Y = A;
endmodule
