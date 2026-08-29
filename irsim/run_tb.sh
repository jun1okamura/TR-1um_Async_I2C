#!/bin/sh
# run_tb.sh -- run the self-checking IRSIM testbench (irsim_tb.cmd, the
# switch-level equivalent of src/i2c_slave_async_tb.v) AND automatically
# judge + display the result in one command, e.g.:
#
#   ./run_tb.sh
#
# is meant to be the IRSIM-side equivalent of the Verilog workflow:
#
#   iverilog -o sim i2c_slave_async.v stdcell_behavioral_stubs.v \
#       i2c_slave_async_tb.v && vvp sim
#
# which runs the simulation and prints the full "[t=..] OK/FAIL: ..."
# report directly. IRSIM's own .cmd language has no conditionals or
# arithmetic, so it cannot total up a pass/fail count on its own the way
# a Verilog testbench can -- this script instead runs IRSIM exactly like
# run_batch.sh does (stdin heredoc, since the "-@ cmdfile" CLI flag is
# broken on this irsim build -- see README.md), saves the raw log, then
# pipes that log through script/check_irsim_tb_log.py, which performs
# the offline PASS/FAIL judgment against irsim_tb_expected.json and
# prints the report.
#
# Usage (from inside irsim/):
#   ./run_tb.sh [prm-file]
# Pass -v as a second arg to also show each individual per-bit sample
# used to reconstruct the read-byte check (see check_irsim_tb_log.py).
#
# Output: irsim_tb_run.log (raw IRSIM output) plus the formatted
# PASS/FAIL report printed to stdout (and its exit code: 0 = all
# checks passed, 1 = at least one failed).

set -eu
cd "$(dirname "$0")"
PRM="${1:-TR-1um.prm}"
SIM="tr_1um_i2c_slave_async.sim"
LOG="irsim_tb_run.log"
VERBOSE="${2:-}"

echo "irsim $PRM $SIM  (running irsim_tb.cmd, log: $LOG)" >&2

irsim "$PRM" "$SIM" > "$LOG" 2>&1 << 'EOF'
@ irsim_tb.cmd
EOF
# NOTE: no explicit "quit" here -- see run_batch.sh; stdin EOF alone is
# enough to make this irsim build exit cleanly.

echo "---- irsim run complete, checking $LOG against irsim_tb_expected.json ----" >&2
python3 ../script/check_irsim_tb_log.py "$LOG" irsim_tb_expected.json $VERBOSE
