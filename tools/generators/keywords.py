"""Generates illegal designs that use a reserved keyword as a variable name,
one for each keyword of the keyword set of IEEE 1800-2023 (Annex B) and one
for each keyword that each version_specifier of 22.14 adds to the set before
it.

The reference model is the keyword tables: 22.14.2 lists the keywords of
"1364-1995", and 22.14.3, 22.14.5, 22.14.6, 22.14.7 and 22.14.8 the ones that
"1364-2001", "1364-2005", "1800-2005", "1800-2009" and "1800-2012" add; 22.14.9
says that "1800-2017" and "1800-2023" add none, so their union is Annex B. A
keyword cannot be used as an unescaped simple identifier (5.6). Without a
begin_keywords directive the keyword set is left to the tool (22.14), so each
design selects its set with begin_keywords and declares `reg <keyword>;`,
which a tool has to reject at that line. "1364-2001-noconfig" (22.14.4) only
removes keywords, and is not tested here.
"""

from common import Case

NAME = "keywords"
VERSION = 1
CHAPTER = 5

# The keywords each version_specifier adds to the one before it.
ADDED = {
    "1364-1995": """
        always and assign begin buf bufif0 bufif1 case casex casez cmos deassign default
        defparam disable edge else end endcase endfunction endmodule endprimitive
        endspecify endtable endtask event for force forever fork function highz0 highz1
        if ifnone initial inout input integer join large macromodule medium module nand
        negedge nmos nor not notif0 notif1 or output parameter pmos posedge primitive
        pull0 pull1 pulldown pullup rcmos real realtime reg release repeat rnmos rpmos
        rtran rtranif0 rtranif1 scalared small specify specparam strong0 strong1 supply0
        supply1 table task time tran tranif0 tranif1 tri tri0 tri1 triand trior trireg
        vectored wait wand weak0 weak1 while wire wor xnor xor
    """,
    "1364-2001": """
        automatic cell config design endconfig endgenerate generate genvar incdir
        include instance liblist library localparam noshowcancelled pulsestyle_ondetect
        pulsestyle_onevent showcancelled signed unsigned use
    """,
    "1364-2005": """
        uwire
    """,
    "1800-2005": """
        alias always_comb always_ff always_latch assert assume before bind bins binsof
        bit break byte chandle class clocking const constraint context continue cover
        covergroup coverpoint cross dist do endclass endclocking endgroup endinterface
        endpackage endprogram endproperty endsequence enum expect export extends extern
        final first_match foreach forkjoin iff ignore_bins illegal_bins import inside
        int interface intersect join_any join_none local logic longint matches modport
        new null package packed priority program property protected pure rand randc
        randcase randsequence ref return sequence shortint shortreal solve static string
        struct super tagged this throughout timeprecision timeunit type typedef union
        unique var virtual void wait_order wildcard with within
    """,
    "1800-2009": """
        accept_on checker endchecker eventually global implies let nexttime reject_on
        restrict s_always s_eventually s_nexttime s_until s_until_with strong
        sync_accept_on sync_reject_on unique0 until until_with untyped weak
    """,
    "1800-2012": """
        implements interconnect nettype soft
    """,
}
CLAUSE = {"1364-1995": "22.14.2", "1364-2001": "22.14.3", "1364-2005": "22.14.5",
          "1800-2005": "22.14.6", "1800-2009": "22.14.7", "1800-2012": "22.14.8"}

# Where a release accepts the declaration (docs/simulator-differences.md).
ACCEPTED_BY = {
    ("1800-2023", "global"): "Verilator 5.052",
    ("1800-2009", "global"): "Verilator 5.052",
    ("1364-1995", "ifnone"): "Verilator 5.052",
}


def added(version: str) -> list[str]:
    return ADDED[version].split()


def annex_b() -> list[str]:
    words = [w for v in ADDED for w in added(v)]
    assert len(words) == len(set(words)) == 248
    return sorted(words)


def case(version: str, keyword: str, lrm: str, chapter: int, why: str) -> Case:
    name = f"test_gen_kw_{version.replace('-', '_')}_{keyword}"
    if version == "1800-2023":
        name = f"test_gen_kw_2023_{keyword}"
    note = ""
    if (version, keyword) in ACCEPTED_BY:
        note = (f" The release {ACCEPTED_BY[version, keyword]} accepts the declaration, "
                "which the list of simulator differences records.")
    if version == "1800-2023":
        note += (" Icarus Verilog 13.0 reports that it ignores the version string "
                 "1800-2023, which it does not know, and keeps its default keyword set, in "
                 "which the word is reserved too.")
    return Case(
        name=name,
        description=f"{keyword} is reserved under begin_keywords \"{version}\" and cannot "
                    f"name a variable",
        lrm=lrm,
        comment=why + note,
        body=f"`begin_keywords \"{version}\"\n"
             f"module {name};\n"
             f"  reg {keyword};  // illegal\n"
             f"endmodule\n"
             f"`end_keywords\n",
        expected="",
        chapter=chapter,
        should_fail_because=f"{keyword} is a reserved keyword in the keyword set that "
                            f"begin_keywords \"{version}\" selects, so it cannot be "
                            f"declared as a variable name",
    )


def cases() -> list[Case]:
    out = []
    for keyword in annex_b():
        out.append(case(
            "1800-2023", keyword, "5.6 B 22.14", 5,
            f"IEEE 1800-2023 §5.6 and Annex B: {keyword} is one of the reserved keywords "
            f"of IEEE 1800-2023, and a keyword cannot be used as an unescaped simple "
            f"identifier. Without begin_keywords the keyword set is left to the tool "
            f"(22.14), so the design selects the 1800-2023 set with begin_keywords and "
            f"declares a variable named {keyword}, which a tool has to reject there."))
    for version, clause in CLAUSE.items():
        for keyword in added(version):
            out.append(case(
                version, keyword, f"{clause} 22.14 5.6", 22,
                f"IEEE 1800-2023 §{clause}: the keyword set that begin_keywords "
                f"\"{version}\" selects reserves {keyword}, and a keyword cannot be "
                f"used as an unescaped simple identifier (5.6). The design selects that "
                f"set and declares a variable named {keyword}, which a tool has to "
                f"reject there."))
    return out
