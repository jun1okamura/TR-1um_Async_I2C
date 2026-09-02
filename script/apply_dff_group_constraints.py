"""
apply_dff_group_constraints.py

Adds the row-buffer functional grouping documented in design_notes.md
section 108.23 as a HARD placement constraint on top of fm_partition.py's
automatic min-cut row partitioner.

Background
----------
insert_row_buffers.py creates one clock buffer per (target_net, row)
pair, where "row" comes directly from fm_multiway_partition()'s output --
a partition chosen purely to minimize net cuts / balance cell width, with
zero awareness of which DFFs will end up sharing that row's buffer. This
is exactly how the row-buffer-loading imbalance that caused the
108.19/108.20 (shreg) and 108.21/108.22 (sda_oe_r) SPICE bugs came about:
FM happened to put 14 unrelated DFFs (7 rx_data + 7 shreg) in the same
physical row, so insert_row_buffers.py faithfully built ONE overloaded
14-fanout buffer for it, and a same-row 0->1 capture failure followed --
purely a side effect of FM optimizing something (general net-cut/width
balance) that has no notion of "these DFFs must share a row because they
will share a clock buffer."

Section 108.23 defined which DFFs SHOULD share a clock buffer, from a
functional-grouping / skew-safety standpoint (shift chain isolated; FSM
counters together; one-shot decision registers together; parallel
capture registers together). This module makes that grouping a real
placement constraint instead of a hope: it clusters each 108.23 group
into a single pseudo-node before running fm_multiway_partition, so FM's
min-cut/balance search can freely place the *groups* wherever it likes,
but can never split a group's members across two different rows. After
partitioning, the cluster's assigned row is copied out to every one of
its real member instances.

fm_multiway_partition_grouped() is a drop-in replacement for
fm_partition.fm_multiway_partition() -- same signature (plus an optional
`groups` argument), same return shape ({instance_name: row_index}).

To actually use it in the pipeline, insert_row_buffers.py's and
gen_placement_nrow_fm.py's `part = fm_multiway_partition(instances,
widths, N_ROWS)` call sites would import this module and call
fm_multiway_partition_grouped(instances, widths, N_ROWS) instead -- not
changed by this script itself (see design_notes.md section 108.28 for
the one-line call-site edit needed at each site, left for a deliberate
follow-up rather than silently rewiring the existing P&R scripts here).

Run standalone: python3 script/apply_dff_group_constraints.py
  -> parses the current pre-row-buffer netlist (src/i2c_slave_async_net.v,
     same one insert_row_buffers.py consumes), runs both the plain
     (baseline) and grouped partition at N_ROWS=4, verifies every 108.23
     group landed in a single row in the grouped run (and, for contrast,
     reports whether/how the baseline run would have split them), prints
     per-row occupancy and net-locality stats for both, and writes
     LEF/row_assignment_v9_dffgrouped.json in the same {instance_name:
     row} format as row_assignment_v9.json.
"""
import json
import pathlib
import sys
from collections import defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from lef_parser import parse_lef  # noqa: E402
from netlist_parser import parse_netlist  # noqa: E402
from fm_partition import fm_multiway_partition, classify_multirow_nets  # noqa: E402

_SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPT_DIR.parent

N_ROWS = 4  # matches insert_row_buffers.py / gen_placement_nrow_fm.py's current N_ROWS

OUT_JSON = str(_REPO_ROOT / "LEF" / "row_assignment_v9_dffgrouped.json")

# design_notes.md section 108.23's functional grouping, by pre-row-buffer
# Yosys instance name (src/i2c_slave_async_net.v numbering, confirmed by
# hand against that file: _504_=addr_match(addr_ok), _505_/6_/7_=
# bit_cnt[0:2], _508_=rw(rw_bit), _509_/10_/11_=phase[0:2], _512_..519_=
# txreg[0:7], _520_..527_=rx_data[0:7], _528_=sda_oe_r, _529_=
# last_bit_pending, _530_..536_=shreg[0:6]).
#
# Groups are named for the clock buffer they are meant to end up sharing
# (matching 108.23's table). "sclN_sda_oe_r" is a singleton, included
# only for documentation -- a group of 1 has nothing to cluster with, so
# it produces no constraint on its own (108.22's fix already gives it a
# dedicated buffer regardless of which row it lands in).
DFF_GROUPS = {
    "clk156_shreg":            ["_530_", "_531_", "_532_", "_533_", "_534_", "_535_", "_536_"],
    "clk156_fsm_state":        ["_505_", "_506_", "_507_", "_509_", "_510_", "_511_"],
    "clk156_oneshot_decision": ["_504_", "_508_", "_529_"],
    "clk156_rx_data":          ["_520_", "_521_", "_522_", "_523_", "_524_", "_525_", "_526_", "_527_"],
    "sclN_txreg_lo":           ["_512_", "_513_", "_514_", "_515_"],
    "sclN_txreg_hi":           ["_516_", "_517_", "_518_", "_519_"],
    "sclN_sda_oe_r":           ["_528_"],
}


def build_grouped_instances(instances, widths, groups):
    """-> (reduced_instances, widths_ext, cluster_members)

    reduced_instances: every ungrouped instance unchanged, plus one
    pseudo-instance per group (typ=name=group name) whose pins are the
    union, across all its members, of every "{member}.{pin}": net entry
    -- enough for fm_partition.build_hypergraph to see every net the
    group touches as belonging to one node, without caring about
    per-member pin identity (build_hypergraph only uses pin VALUES, i.e.
    net names, to build hyperedges; pin names/keys are never inspected).

    widths_ext: widths dict extended with one entry per group name, equal
    to the sum of its members' real cell widths, so fm_partition's
    `widths[typ]` weight lookup works unmodified on the pseudo-instance
    (typ is set equal to the group name for cluster pseudo-instances).

    cluster_members: {group_name: [real_instance_name, ...]}, for
    expanding the partition result back afterward.

    Raises ValueError (rather than silently under-constraining) if a
    listed member is missing from the parsed netlist, or if an instance
    name is listed in more than one group.
    """
    name_to_group = {}
    for gname, members in groups.items():
        for m in members:
            if m in name_to_group:
                raise ValueError(
                    f"{m!r} listed in two groups: {name_to_group[m]!r} and {gname!r}")
            name_to_group[m] = gname

    by_name = {name: (typ, name, pins) for typ, name, pins in instances}
    missing = [m for g in groups.values() for m in g if m not in by_name]
    if missing:
        raise ValueError(f"group members not found in netlist: {missing}")

    grouped = defaultdict(list)
    passthrough = []
    for typ, name, pins in instances:
        gname = name_to_group.get(name)
        if gname is None:
            passthrough.append((typ, name, pins))
        else:
            grouped[gname].append((typ, name, pins))

    widths_ext = dict(widths)
    cluster_members = {}
    cluster_instances = []
    for gname, members in grouped.items():
        cluster_members[gname] = [n for _t, n, _p in members]
        merged_pins = {}
        for typ, name, pins in members:
            for pname, net in pins.items():
                merged_pins[f"{name}.{pname}"] = net
        cluster_instances.append((gname, gname, merged_pins))
        widths_ext[gname] = sum(widths[t] for t, _n, _p in members)

    return passthrough + cluster_instances, widths_ext, cluster_members


def _domain_of(group_name):
    """Groups sharing a clock domain are named with a common prefix before
    the first underscore ("clk156_..." / "sclN_..."). insert_row_buffers.py
    builds one buffer per (target_net, row) -- two DFF_GROUPS in the SAME
    domain landing on the SAME row would still end up sharing one
    buffer, silently recreating the exact overload bug this whole
    mechanism exists to prevent. Intra-group cohesion alone (guaranteed
    by clustering, above) does not prevent that; _resolve_domain_collisions
    below does."""
    return group_name.split("_", 1)[0]


def _resolve_domain_collisions(cluster_rows, groups, n_rows):
    """cluster_rows: {group_name: row} as chosen by FM on the clustered
    hypergraph. Where two-or-more groups sharing a domain (see
    _domain_of) were given the same row, reassign that domain's groups to
    mutually distinct rows: brute-force every injective groups->rows
    mapping (small search space -- at most a handful of groups per
    domain), scored by how many groups have to move off FM's original
    choice, and keep the lowest-disruption mapping. Ties keep FM's
    choice for as many groups as possible by construction (a mapping
    that matches more of FM's original choices scores strictly lower
    disruption). Domains with no collision are left untouched."""
    from itertools import permutations

    by_domain = defaultdict(list)
    for g in groups:
        by_domain[_domain_of(g)].append(g)

    resolved = dict(cluster_rows)
    for domain, gnames in by_domain.items():
        rows_used = [resolved[g] for g in gnames]
        if len(set(rows_used)) == len(rows_used):
            continue  # already all-distinct, nothing to do
        if len(gnames) > n_rows:
            raise ValueError(
                f"domain {domain!r} has {len(gnames)} groups but only "
                f"{n_rows} rows exist -- cannot give each its own row")
        best_cost, best_assignment = None, None
        for candidate_rows in permutations(range(n_rows), len(gnames)):
            cost = sum(1 for g, r in zip(gnames, candidate_rows) if r != resolved[g])
            if best_cost is None or cost < best_cost:
                best_cost, best_assignment = cost, dict(zip(gnames, candidate_rows))
        resolved.update(best_assignment)
        print(f"  domain {domain!r}: row collision resolved "
              f"({best_cost} group(s) moved off FM's initial choice) -> "
              + ", ".join(f"{g}=row{best_assignment[g]}" for g in gnames))
    return resolved


def fm_multiway_partition_grouped(instances, widths, n_rows, groups=DFF_GROUPS, balance_tol=0.05):
    """Drop-in replacement for fm_partition.fm_multiway_partition() that
    guarantees (a) every `groups` member set lands in a single row, AND
    (b) no two groups sharing a clock domain (see _domain_of) land on the
    SAME row -- both needed for the resulting row assignment to actually
    prevent 108.19-/108.21-style buffer overload once insert_row_buffers.py
    runs on it.

    Groups of size 1 pass straight through the clustering machinery
    unchanged (a 1-element cluster behaves identically to not clustering
    it at all), so it is safe to list singleton groups purely for
    documentation, as DFF_GROUPS does for sclN_sda_oe_r.
    """
    reduced, widths_ext, cluster_members = build_grouped_instances(instances, widths, groups)
    part = fm_multiway_partition(reduced, widths_ext, n_rows, balance_tol=balance_tol)

    cluster_rows = {g: part[g] for g in groups}
    cluster_rows = _resolve_domain_collisions(cluster_rows, groups, n_rows)

    full_part = {}
    for name, row in part.items():
        if name in cluster_members:
            continue  # replaced below using the (possibly collision-resolved) cluster_rows
        full_part[name] = row
    for gname, members in cluster_members.items():
        for member in members:
            full_part[member] = cluster_rows[gname]
    return full_part


def _report_groups(part, groups, label):
    print(f"108.23 group check ({label}):")
    all_ok = True
    group_row = {}
    for gname, members in groups.items():
        rows = sorted({part[m] for m in members})
        ok = len(rows) == 1
        all_ok = all_ok and ok
        marker = "OK" if ok else "*** SPLIT ACROSS ROWS ***"
        print(f"  {gname:<26} members={len(members):<2} row(s)={rows}  {marker}")
        if ok:
            group_row[gname] = rows[0]

    by_domain = defaultdict(list)
    for gname, row in group_row.items():
        by_domain[_domain_of(gname)].append((gname, row))
    for domain, entries in by_domain.items():
        rows = [r for _g, r in entries]
        if len(set(rows)) != len(rows):
            all_ok = False
            print(f"  *** DOMAIN COLLISION *** {domain!r}: "
                  + ", ".join(f"{g}=row{r}" for g, r in entries))
    return all_ok


if __name__ == "__main__":
    macros = parse_lef()
    widths = {name: m["size"][0] for name, m in macros.items()}
    net = parse_netlist()
    instances = net["instances"]
    print(f"parsed {len(instances)} instances")

    print(f"\n=== baseline: plain fm_multiway_partition (N_ROWS={N_ROWS}) ===")
    part_baseline = fm_multiway_partition(instances, widths, N_ROWS)
    _report_groups(part_baseline, DFF_GROUPS, "baseline, no constraint")

    print(f"\n=== constrained: fm_multiway_partition_grouped (N_ROWS={N_ROWS}) ===")
    part_grouped = fm_multiway_partition_grouped(instances, widths, N_ROWS)
    all_ok = _report_groups(part_grouped, DFF_GROUPS, "grouped, must all be OK")
    if not all_ok:
        print("ERROR: a group was split even after clustering -- this should not happen",
              file=sys.stderr)
        sys.exit(1)

    row_counts = defaultdict(int)
    for r in part_grouped.values():
        row_counts[r] += 1
    print("\nrow occupancy (all instances, grouped run):")
    for r in sorted(row_counts):
        print(f"  row{r}: {row_counts[r]} instances")

    cut_before = classify_multirow_nets(instances, part_baseline, N_ROWS)
    cut_after = classify_multirow_nets(instances, part_grouped, N_ROWS)
    print(f"\nnet locality, baseline:   {cut_before}")
    print(f"net locality, grouped:    {cut_after}")

    with open(OUT_JSON, "w") as f:
        json.dump(part_grouped, f, indent=1, sort_keys=True)
    print(f"\nwrote {OUT_JSON} ({len(part_grouped)} instances)")
