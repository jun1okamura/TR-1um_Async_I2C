#!/bin/sh
# run_batch.sh -- run IRSIM non-interactively (stdin redirection instead
# of the command-line "-@ cmdfile" flag, which a real run on this
# project's irsim 9.7.121 build confirmed gets misparsed as a netlist
# and produces a wall of syntax errors -- see irsim/README.md).
#
# This instead feeds the SAME "@ file" commands you'd type by hand at
# the interactive "irsim>" prompt, just via stdin redirection -- IRSIM's
# prompt reads from stdin either way, so this should behave identically
# to typing them manually, but let the real run confirm that (not
# verified with an actual irsim binary this session -- no irsim
# available in the sandbox this was written in).
#
# Usage (from inside irsim/):
#   ./run_batch.sh [prm-file]
# Output goes to irsim_batch_run.log (both stdout and stderr).

set -eu
cd "$(dirname "$0")"
PRM="${1:-TR-1um.prm}"
SIM="tr_1um_i2c_slave_async.sim"
LOG="irsim_batch_run.log"

echo "irsim $PRM $SIM  (stdin-driven batch run, log: $LOG)"

irsim "$PRM" "$SIM" > "$LOG" 2>&1 << 'EOF'
@ irsim_reset_check.cmd
@ irsim_test_main.cmd
@ irsim_test_negative.cmd
EOF
# NOTE: no explicit "quit" here -- a real run confirmed this build's irsim
# doesn't recognize "quit" as a command at this point ("unrecognized
# command: quit") even though everything before it ran correctly; stdin
# hitting EOF (heredoc ends) is enough to make irsim exit cleanly on its
# own, so the extra line was just producing a harmless but confusing
# warning at the end of the log.

echo "done -- see $LOG"
