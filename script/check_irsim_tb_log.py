#!/usr/bin/env python3
"""
check_irsim_tb_log.py -- automatically verify a real IRSIM run's log
against a generated *_expected.json (see gen_irsim_verilog_equiv_tb.py /
gen_irsim_cmd_v9.py's CmdGen.checked_dump()), and print a PASS/FAIL
report equivalent to src/i2c_slave_async_tb.v's check() task / errors
counter / final RESULT line.

IRSIM's own .cmd language has no conditionals or arithmetic, so a .cmd
file alone can only DUMP node values to the log for a human to read --
it cannot itself decide pass/fail or total up an error count the way a
Verilog testbench can. This script does that comparison offline, after
the fact, against a real run's plain-text log.

Usage:
    python3 check_irsim_tb_log.py <logfile> <expected.json> [-v]

Output mirrors src/i2c_slave_async_tb.v's own $display format, e.g.:
    [t=240000] OK:                                        busy asserted after START
    [t=960000] OK:                             slave ACKed matching address (write)
    ...
    ---- RESULT ----
    All 14 checks PASSED
-v/--verbose additionally prints each individual per-bit [sample] line
used to reconstruct the multi-bit "read byte == 0x.." checks (suppressed
by default so the headline count lines up 1:1 with the Verilog output).

How it works: every `d node1 node2 ...` command in the generated .cmd
produces one block of "node=value" output in the log, framed by
"time = ...ns" lines before and after (IRSIM echoes the current time
around every command). This script finds each such block, in order, and
zips it 1:1 against the ordered list of dump records in <expected.json>
(recorded by CmdGen.d()/checked_dump() in the SAME order they were
emitted while generating the .cmd) -- no timestamps or special log
markers are needed, just positional correspondence, which is exact as
long as the log is from a run of the matching .cmd file start-to-finish.
"""
import json
import re
import sys

TIME_RE = re.compile(r'^\s*time\s*=\s*([0-9.]+)')
ASSIGN_TOKEN_RE = re.compile(r'^([^\s=]+)=(\S*)$')
MSG_FIELD_WIDTH = 65  # visual right-justify width, matching src/i2c_slave_async_tb.v's $display("[t=%0t] %s: %s", ...) look


def strip_prompt(line):
    # IRSIM's interactive prompt "irsim>" sometimes prefixes the next
    # line of output on the same physical line (e.g. "irsim> time = ...").
    if line.startswith('irsim>'):
        line = line[len('irsim>'):]
    return line.strip()


def parse_log(path):
    """Returns an ordered list of (time_str_or_None, {node: value_str})
    tuples, one per `d` command's actual output block found in the log.
    The timestamp recorded is the "time=" line that CLOSES the block
    (IRSIM echoes the same current time both before and after a command
    that doesn't itself advance simulated time, like `d`), used purely
    for display -- matching src/i2c_slave_async_tb.v's "[t=%0t] ..."
    style is cosmetic, not part of the pass/fail comparison itself."""
    dumps = []
    buf = {}
    have_content = False
    with open(path) as f:
        for raw in f:
            line = strip_prompt(raw)
            if not line:
                continue
            m_time = TIME_RE.match(line)
            if m_time:
                if have_content:
                    dumps.append((m_time.group(1), buf))
                    buf = {}
                    have_content = False
                continue
            # Skip known non-dump chatter (header/banner/error lines).
            if line.startswith('*') or line.startswith('|'):
                continue
            if line.startswith('Using default name') or line.startswith('Read ') \
               or 'nodes; transistors' in line or line.startswith('parallel txtors') \
               or line.startswith('Unexpected first line') or 'unrecognized command' in line:
                continue
            # Otherwise, try to parse as one or more "node=value" tokens.
            toks = line.split()
            parsed_any = False
            for t in toks:
                m = ASSIGN_TOKEN_RE.match(t)
                if m:
                    buf[m.group(1)] = m.group(2)
                    parsed_any = True
            if parsed_any:
                have_content = True
    if have_content:
        dumps.append((None, buf))
    return dumps


def fmt_line(time_str, status, label):
    t = time_str if time_str is not None else "?"
    return f"[t={t}] {status}:{label:>{MSG_FIELD_WIDTH}}"


def val_matches(actual_str, expect_int):
    if actual_str is None:
        return False, "node not found in dump"
    if actual_str.lower() in ('x',):
        return False, "undefined (X)"
    try:
        actual_int = int(actual_str)
    except ValueError:
        return False, f"unparseable value {actual_str!r}"
    return (actual_int == expect_int), None


def main():
    args = [a for a in sys.argv[1:] if a not in ('-v', '--verbose')]
    if len(args) != 2:
        print(f"usage: {sys.argv[0]} <logfile> <expected.json> [-v]", file=sys.stderr)
        sys.exit(2)
    logfile, expected_path = args[0], args[1]

    with open(expected_path) as f:
        spec = json.load(f)
    checks = spec["checks"]
    groups = spec.get("groups", {})

    dumps = parse_log(logfile)

    if len(dumps) != len(checks):
        print(f"** WARNING: log has {len(dumps)} dump blocks but expected.json "
              f"has {len(checks)} recorded d()/checked_dump() calls. **")
        print("Results below only cover the shorter of the two -- this usually "
              "means the log is from a partial/different run than the .cmd that "
              "generated expected.json (e.g. cut short, or from an older/newer "
              "revision of the script). Re-run the exact .cmd this JSON was "
              "generated alongside.\n")

    n = min(len(dumps), len(checks))
    headline_total = 0
    headline_failed = 0
    group_bits = {}   # group name -> list of actual bit values
    group_time = {}   # group name -> time of the LAST sample in that group
    group_last_idx = {}  # group name -> index (in checks[]) of its last sample
    # (index, text) pairs, sorted by index at the end so a group's
    # synthesized headline check prints inline at the position where its
    # last sample occurred -- matching the Verilog testbench's natural
    # chronological ordering instead of trailing after every other check.
    out_lines = []

    verbose = "-v" in sys.argv or "--verbose" in sys.argv

    for i in range(n):
        check = checks[i]
        time_str, dump = dumps[i]
        label = check["label"]
        expect = check["expect"]
        group = check["group"]

        if expect is None:
            continue  # informational dump only (e.g. from start()'s internal d() calls)

        all_ok = True
        details = []
        for node, exp_val in expect.items():
            actual = dump.get(node)
            ok, reason = val_matches(actual, exp_val)
            if not ok:
                all_ok = False
                details.append(f"{node}: expected={exp_val} actual={actual!r}"
                                + (f" ({reason})" if reason else ""))

        if group:
            # Detail-only: record for later synthesis into one headline
            # check (matching how i2c_slave_async_tb.v's read_byte() only
            # asserts the final reconstructed byte, not each sampled bit).
            bit_node = list(expect.keys())[0]
            group_bits.setdefault(group, []).append(dump.get(bit_node))
            group_time[group] = time_str
            group_last_idx[group] = i
            if verbose:
                status = "ok" if all_ok else "MISMATCH"
                out_lines.append((i, f"  [sample] {label}: {status}"
                                  + ("" if all_ok else " (" + "; ".join(details) + ")")))
            continue

        headline_total += 1
        if all_ok:
            out_lines.append((i, fmt_line(time_str, "OK", label)))
        else:
            headline_failed += 1
            out_lines.append((i, fmt_line(time_str, "FAIL", label)
                               + "  (" + "; ".join(details) + ")"))

    # Synthesized group-level checks (e.g. the reconstructed read byte),
    # matching how i2c_slave_async_tb.v only asserts the final byte, not
    # each individually-sampled bit. Sorted in with the headline checks
    # above by the index of the group's last sample.
    for gname, meta in groups.items():
        bits = group_bits.get(gname)
        time_str = group_time.get(gname)
        idx = group_last_idx.get(gname, n)
        label = meta["label"]
        headline_total += 1
        if not bits or any(b is None for b in bits):
            headline_failed += 1
            out_lines.append((idx, fmt_line(time_str, "FAIL", label)
                               + f"  (incomplete sample data: {bits})"))
            continue
        try:
            if meta.get("bit_order") == "msb_first":
                actual_val = 0
                for b in bits:
                    actual_val = (actual_val << 1) | int(b)
            else:
                actual_val = 0
                for idx2, b in enumerate(bits):
                    actual_val |= int(b) << idx2
        except ValueError:
            headline_failed += 1
            out_lines.append((idx, fmt_line(time_str, "FAIL", label)
                               + f"  (non-binary sample in {bits})"))
            continue
        if actual_val == meta["target"]:
            out_lines.append((idx, fmt_line(time_str, "OK", label)
                               + f"  (got 0x{actual_val:02X})"))
        else:
            headline_failed += 1
            out_lines.append((idx, fmt_line(time_str, "FAIL", label)
                               + f"  (expected 0x{meta['target']:02X}, "
                               f"got 0x{actual_val:02X}; bits={bits})"))

    for _, text in sorted(out_lines, key=lambda p: p[0]):
        print(text)

    print("\n---- RESULT ----")
    if headline_failed == 0:
        print(f"All {headline_total} checks PASSED")
    else:
        print(f"{headline_failed} of {headline_total} check(s) FAILED")
    sys.exit(1 if headline_failed else 0)


if __name__ == "__main__":
    main()
