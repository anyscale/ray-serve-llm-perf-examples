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


# 1P-TP4 : 1D-TP4 (symmetric)
echo "Running 1P-TP4 : 1D-TP4 (symmetric, highest TP)..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 4 --d-num 1 --d-tp 4 --use-ucx
sleep 30
./run_bm.sh -e pd_p1xtp4-d1xtp4 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 1P-TP2 : 1D-TP4 (asymmetric, lower prefill TP)
echo "Running 1P-TP2 : 1D-TP4 (asymmetric, lower P TP)..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 2 --d-num 1 --d-tp 4 --use-ucx
sleep 30
./run_bm.sh -e pd_p1xtp2-d1xtp4 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 2P-TP2 : 1D-TP4 (more prefill capacity)
echo "Running 2P-TP2 : 1D-TP4 (more prefill capacity)..."
python launch_gptoss.py --mode pd-pack --p-num 2 --p-tp 2 --d-num 1 --d-tp 4 --use-ucx
sleep 30
./run_bm.sh -e pd_p2xtp2-d1xtp4 -t concurrency --itl ${ITL} --otl ${OTL}
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

# P:TP2, D:TP2 with various ratios
echo "Testing P:TP2, D:TP2 ratios (emphasizing ratio importance)..."

# 3:1 ratio (prefill-heavy)
echo "  3:1 ratio (3P-TP2 : 1D-TP2)..."
python launch_gptoss.py --mode pd-pack --p-num 3 --p-tp 2 --d-num 1 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_p3xtp2-d1xtp2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 2:1 ratio
echo "  2:1 ratio (2P-TP2 : 1D-TP2)..."
python launch_gptoss.py --mode pd-pack --p-num 2 --p-tp 2 --d-num 1 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_p2xtp2-d1xtp2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 1:1 ratio
echo "  1:1 ratio (1P-TP2 : 1D-TP2)..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 2 --d-num 1 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_p1xtp2-d1xtp2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 1:2 ratio (decode-heavy)
echo "  1:2 ratio (1P-TP2 : 2D-TP2)..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 2 --d-num 2 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_p1xtp2-d2xtp2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

# 1:3 ratio (decode-heavy)
echo "  1:3 ratio (1P-TP2 : 3D-TP2)..."
python launch_gptoss.py --mode pd-pack --p-num 1 --p-tp 2 --d-num 3 --d-tp 2 --use-ucx
sleep 30
./run_bm.sh -e pd_p1xtp2-d3xtp2 -t concurrency --itl ${ITL} --otl ${OTL}
serve shutdown -y > /dev/null 2>&1
sleep 10

echo ""
echo "Part 2 complete. Expected: Optimal ratio shifts with throughput regime."
echo ""
echo "=========================================="
echo "PD Ratio and TP exploration complete!"
echo "=========================================="
echo ""
echo "Key observations to look for:"
echo "  1. Ratio matters: Optimal P:D ratio shifts with throughput regime"
echo "  2. TP4-TP4: PD can beat collocated in token efficiency"
echo "  3. TP2-TP2: Dynamic ratio adjustment needed as traffic scales"
echo "  4. Asymmetric configs: P-TP2 can work with D-TP4"
echo ""
echo "Generating visualizations..."
echo ""

# Part 1: D:TP4 configs visualization
echo "Visualizing Part 1: D:TP4 configurations..."
python viz.py \
  --exps \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_baseline_2xtp4 \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_pd_p1xtp4-d1xtp4 \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_pd_p1xtp2-d1xtp4 \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_pd_p2xtp2-d1xtp4 \
  --plot-path plots/pd_ratio_dtp4 \
  --latency-mode token \
  --use-normalized \
  --log-latency \
  --log-concurrency \
  --throughput-metric output

echo ""
echo "Part 1 visualization saved to: plots/pd_ratio_dtp4/comprehensive_analysis.png"
echo ""

# Part 2: D:TP2 ratios visualization
echo "Visualizing Part 2: D:TP2 ratios..."
python viz.py \
  --exps \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_baseline_4xtp2 \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_pd_p3xtp2-d1xtp2 \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_pd_p2xtp2-d1xtp2 \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_pd_p1xtp2-d1xtp2 \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_pd_p1xtp2-d2xtp2 \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_pd_p1xtp2-d3xtp2 \
  --plot-path plots/pd_ratio_dtp2 \
  --latency-mode token \
  --use-normalized \
  --log-latency \
  --log-concurrency \
  --throughput-metric output

echo ""
echo "Part 2 visualization saved to: plots/pd_ratio_dtp2/comprehensive_analysis.png"
echo ""
echo "=========================================="
