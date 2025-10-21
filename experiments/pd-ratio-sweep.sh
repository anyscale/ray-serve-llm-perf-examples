#!/bin/bash
# PD Ratio and TP Configuration Exploration
#
# This experiment explores how P:D ratios and TP combinations affect PD performance.
# Based on Section 2 of the story, we test:
#
# For D:TP4 (decode with TP=4):
#   - 1P-TP4 : 1D-TP4  (symmetric, highest TP)
#   - 1P-TP2 : 1D-TP4  (asymmetric, lower P TP)
#   - 2P-TP2 : 1D-TP4  (more prefill capacity)
#
# For D:TP2 (decode with TP=2):
#   - Various P:TP2 : D:TP2 ratios (3:1, 2:1, 1:1, 1:2, 1:3)
#   - Various P:TP1 : D:TP2 combinations
#
# Key takeaways to demonstrate:
# 1. Ratio is very important - dynamic adjustment needed as traffic scales
# 2. PD can beat collocated in token efficiency (especially TP4-TP4)
# 3. Optimal ratio shifts with throughput regime

set -e

ITL=5000
OTL=250

echo "=========================================="
echo "PD Ratio and TP Configuration Exploration"
echo "ITL:OTL = ${ITL}:${OTL}"
echo "=========================================="
echo ""

#==============================================================================
# Part 1: D:TP4 Configurations (highest decode performance)
#==============================================================================

echo "=========================================="
echo "Part 1: D:TP4 Configurations"
echo "Testing decode with TP=4"
echo "=========================================="
echo ""

# Baseline: Collocated TP=4 for comparison
echo "Running collocated TP=4 baseline..."
python launch_gptoss.py --mode collocated --tp 4 --num-replicas 2
sleep 30
./run_bm.sh -e baseline_tp4 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 1P-TP4 : 1D-TP4 (symmetric)
echo "Running 1P-TP4 : 1D-TP4 (symmetric, highest TP)..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
sleep 30
./run_bm.sh -e pd_1p4-1d4 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 1P-TP2 : 1D-TP4 (asymmetric, lower prefill TP)
echo "Running 1P-TP2 : 1D-TP4 (asymmetric, lower P TP)..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 2 --d-num 1 --d-tp 4 --use-ucx
sleep 30
./run_bm.sh -e pd_1p2-1d4 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 2P-TP2 : 1D-TP4 (more prefill capacity)
echo "Running 2P-TP2 : 1D-TP4 (more prefill capacity)..."
python launch_gptoss.py --mode pd-pack --p-num 2 --p-tp 2 --d-num 1 --d-tp 4 --use-ucx
sleep 30
./run_bm.sh -e pd_2p2-1d4 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

echo ""
echo "Part 1 complete. Expected: 1P4-1D4 should beat collocated TP4 in efficiency."
echo ""

#==============================================================================
# Part 2: D:TP2 Configurations - Ratio Exploration
#==============================================================================

echo "=========================================="
echo "Part 2: D:TP2 Ratio Exploration"
echo "Testing different P:D ratios with TP=2"
echo "=========================================="
echo ""

# Baseline: Collocated TP=2 for comparison
echo "Running collocated TP=2 baseline..."
python launch_gptoss.py --mode collocated --tp 2 --num-replicas 4
sleep 30
./run_bm.sh -e baseline_tp2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# P:TP2, D:TP2 with various ratios
echo "Testing P:TP2, D:TP2 ratios (emphasizing ratio importance)..."

# 3:1 ratio (prefill-heavy)
echo "  3:1 ratio (3P-TP2 : 1D-TP2)..."
python launch_gptoss.py --mode pd-pack --p-num 3 --p-tp 2 --d-num 1 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_3p2-1d2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 2:1 ratio
echo "  2:1 ratio (2P-TP2 : 1D-TP2)..."
python launch_gptoss.py --mode pd-pack --p-num 2 --p-tp 2 --d-num 1 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_2p2-1d2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 1:1 ratio
echo "  1:1 ratio (1P-TP2 : 1D-TP2)..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 2 --d-num 1 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_1p2-1d2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 1:2 ratio (decode-heavy)
echo "  1:2 ratio (1P-TP2 : 2D-TP2)..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 2 --d-num 2 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_1p2-2d2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 1:3 ratio (decode-heavy)
echo "  1:3 ratio (1P-TP2 : 3D-TP2)..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 2 --d-num 3 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_1p2-3d2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

echo ""
echo "Part 2 complete. Expected: Optimal ratio shifts with throughput regime."
echo ""

#==============================================================================
# Part 3: P:TP1, D:TP2 Configurations
#==============================================================================

echo "=========================================="
echo "Part 3: P:TP1, D:TP2 Configurations"
echo "Testing lower prefill TP with TP2 decode"
echo "=========================================="
echo ""

# 1P-TP1 : 1D-TP2
echo "Running 1P-TP1 : 1D-TP2..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 1 --d-num 1 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_1p1-1d2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 2P-TP1 : 1D-TP2
echo "Running 2P-TP1 : 1D-TP2..."
python launch_gptoss.py --mode pd-pack --p-num 2 --p-tp 1 --d-num 1 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_2p1-1d2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 4P-TP1 : 1D-TP2
echo "Running 4P-TP1 : 1D-TP2..."
python launch_gptoss.py --mode pd-pack --p-num 4 --p-tp 1 --d-num 1 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_4p1-1d2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

echo ""
echo "=========================================="
echo "PD Ratio and TP exploration complete!"
echo "=========================================="
echo ""
echo "Key observations to look for:"
echo "  1. Ratio matters: Optimal P:D ratio shifts with throughput regime"
echo "  2. TP4-TP4: PD can beat collocated in token efficiency"
echo "  3. TP2-TP2: Dynamic ratio adjustment needed as traffic scales"
echo "  4. Lower P TP: Can work with higher D TP (asymmetric configs)"
echo ""
echo "Visualization commands:"
echo ""
echo "# Compare D:TP4 configs:"
echo "python viz.py --exps \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_2xtp4_baseline_tp4 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_1xtp4-1xtp4_pd_1p4-1d4 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_1xtp2-1xtp4_pd_1p2-1d4 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_2xtp2-1xtp4_pd_2p2-1d4"
echo ""
echo "# Compare D:TP2 ratios:"
echo "python viz.py --exps \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_4xtp2_baseline_tp4 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_3xtp2-1xtp2_pd_3p2-1d2 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_2xtp2-1xtp2_pd_2p2-1d2 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_1xtp2-1xtp2_pd_1p2-1d2 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_1xtp2-2xtp2_pd_1p2-2d2 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_1xtp2-3xtp2_pd_1p2-3d2"
echo ""
echo "# Compare P:TP1, D:TP2 configs:"
echo "python viz.py --exps \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_1xtp1-1xtp2_pd_1p1-1d2 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_2xtp1-1xtp2_pd_2p1-1d2 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_4xtp1-1xtp2_pd_4p1-1d2"
echo ""
echo "=========================================="
