| irsim_debug_rw_addrmatch.cmd -- follow-up diagnostic.
| irsim_reset_check.cmd (with the BUFTH force/release fix) now shows
| busy/sda_oe(N45)/N58 correctly resolved and HOLDING at 0/0/1 even after
| rst_n releases -- the BUFTH fix worked for that chain. But rw/addr_match
| (both DFFRB, RSTB=$28, NOT the busy-gated group) go from a correct 0
| during reset-assert to X right after release.
|
| Why "correct 0 during assert" was misleading: while rst_n=0,
|   $28 = NOR2($813, $702), $702 = INV(rst_n) = 1 while rst_n=0
|   -> NOR2(anything, 1) = 0 by domination, regardless of $813's real
|   value. So $28=0 during assert does NOT prove $813's chain has
|   actually resolved -- same illusion pattern as busy/$695 in 76.10.
|
| Once rst_n releases, $702 flips to 0, removing the domination:
|   $28 = NOR2($813, 0) = NOT($813)  -- now genuinely depends on $813.
|   $813 = NOR2($703, $697)          [X$369]
|   $697 = BUF_X1(BUFTH(sda_in)=N37) -- N37 now resolves via the BUFTH
|          fix, so $697 should resolve almost immediately (plain buffer,
|          no feedback).
|   $703 = NAND2($666, $704)         [X$343]
|   $666 = BUF_X1(BUFTH(scl)=N712)   -- also now resolves via the fix.
|   $704 = DEL1($697)                [X$312]  <- intentional delay
|          element, real L=2u transistor. Only had ~8000ns of $697=1
|          BEFORE release (since $697 resolves at ~t=40ns once BUFTH is
|          fixed), so if it needs longer than that to settle, watching
|          well past release (not just 100ns like irsim_reset_check.cmd)
|          should show it catching up -- or reveal a real ternary
|          deadlock of its own if it never does.
| $702  = INV(rst_n)                 [X$377]

stepsize 20
h Vdd
l Gnd
h N58
h N102
l N26
l N19
l N21
l N22
l N57
l N103
l N72
l N68
l N106
l XN3.XN166.N2
l XN3.XN311.N2
s
x XN3.XN166.N2
x XN3.XN311.N2
s 8000
| ---- t=8020ns, reset still asserted, chain should be settled by now ----
d N106 XN3.N37 XN3.N697 XN3.N712 XN3.N666 XN3.N704 XN3.N703 XN3.N702 XN3.N813 XN3.N28 XN3.busy N45 XN3.rw XN3.addr_match
h N106
s 100
| ---- t=8120ns, 100ns after release (matches irsim_reset_check.cmd) ----
d N106 XN3.N37 XN3.N697 XN3.N712 XN3.N666 XN3.N704 XN3.N703 XN3.N702 XN3.N813 XN3.N28 XN3.busy N45 XN3.rw XN3.addr_match
s 900
| ---- t=9020ns, 1000ns after release ----
d N106 XN3.N37 XN3.N697 XN3.N712 XN3.N666 XN3.N704 XN3.N703 XN3.N702 XN3.N813 XN3.N28 XN3.busy N45 XN3.rw XN3.addr_match
s 4000
| ---- t=13020ns, 5000ns after release ----
d N106 XN3.N37 XN3.N697 XN3.N712 XN3.N666 XN3.N704 XN3.N703 XN3.N702 XN3.N813 XN3.N28 XN3.busy N45 XN3.rw XN3.addr_match
s 10000
| ---- t=23020ns, 15000ns after release (in case DEL1 just needs a lot more time) ----
d N106 XN3.N37 XN3.N697 XN3.N712 XN3.N666 XN3.N704 XN3.N703 XN3.N702 XN3.N813 XN3.N28 XN3.busy N45 XN3.rw XN3.addr_match

| end of irsim_debug_rw_addrmatch.cmd
