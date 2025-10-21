#!/bin/bash
# Pack vs Spread - Network Impact on PD Performance
#
# This experiment demonstrates how network configuration affects multi-node PD.
# We compare the same 1P-TP4:1D-TP4 configuration in three scenarios:
#
# 1. Pack (same node): UCX uses cuda_ipc for intra-node transfer
# 2. Spread with good network: UCX uses SRD backend on EFA (proper config)
# 3. Spread with bad network: Force TCP to show impact of misconfiguration
#
# Key takeaway: If network bandwidth is good (SRD), pack and spread should be
# nearly identical. Bad network (TCP fallback) shows significant degradation.

set -e

ITL=5000
OTL=250

echo "=========================================="
echo "Pack vs Spread - Network Impact"
echo "ITL:OTL = ${ITL}:${OTL}"
echo "Config: 1P-TP4 : 1D-TP4"
echo "=========================================="
echo ""


#==============================================================================
# Step 1: Pack mode (same node, cuda_ipc)
#==============================================================================

echo "=========================================="
echo "Step 1: Pack Mode (same node)"
echo "=========================================="
echo ""
echo "UCX will use cuda_ipc for intra-node KV cache transfer"
echo ""

python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
sleep 30
./run_bm.sh -e pack_1p4-1d4 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

echo ""
echo "Pack mode complete."
echo ""

#==============================================================================
# Step 2: Spread mode with good network (SRD)
#==============================================================================

echo "=========================================="
echo "Step 2: Spread Mode (cross-node, SRD)"
echo "=========================================="
echo ""
echo "UCX will use SRD backend on EFA for cross-node transfer"
echo "Expected: Similar performance to pack if network is good"
echo ""

python launch_gptoss.py --mode pd-spread --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
sleep 30
./run_bm.sh -e spread_srd_1p4-1d4 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

echo ""
echo "Spread mode (SRD) complete."
echo ""

#==============================================================================
# Step 3: Spread mode with bad network (forced TCP)
#==============================================================================

echo "=========================================="
echo "Step 3: Spread Mode (cross-node, TCP)"
echo "=========================================="
echo ""
echo "Forcing UCX to use TCP to demonstrate bad network impact"
echo "Expected: Significant performance degradation"
echo ""

# Force TCP transport by setting UCX_TLS environment variable
export UCX_TLS="tcp"

python launch_gptoss.py --mode pd-spread --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
sleep 30
./run_bm.sh -e spread_tcp_1p4-1d4 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1

# Unset UCX_TLS for future runs
unset UCX_TLS
sleep 10

echo ""
echo "Spread mode (TCP) complete."
echo ""

echo ""
echo "=========================================="
echo "Pack vs Spread experiments complete!"
echo "=========================================="
echo ""
echo "Expected observations:"
echo "  1. Pack ≈ Spread (SRD): Network properly configured"
echo "  2. Spread (TCP) << Pack: Bad network severely degrades performance"
echo "  3. Pack/Spread may beat TP8 collocated in efficiency"
echo ""
echo "Visualization command:"
echo "python viz.py --compare-dirs \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_1xtp4-1xtp4_pack_* \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_1xtp4-1xtp4_spread_srd_* \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_1xtp4-1xtp4_spread_tcp_*"
echo ""
echo "Key takeaway: Proper network configuration (SRD on EFA) is critical."
echo "Use debug/test_nixl_connector_ray.py to validate network before benchmarking."
echo "=========================================="
