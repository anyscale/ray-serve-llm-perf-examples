#!/bin/bash
# TP Baselines - Understanding TTFT vs TPOT Trade-offs
#
# This experiment establishes collocated baselines to understand:
# - TPOT (decode performance): TP4 > TP2 > TP1
# - TTFT (prefill performance): 
#   * Low concurrency: TP2 > TP4 > TP1
#   * High concurrency: TP1 > TP2 > TP4
# - Throughput efficiency: TP4 > TP2 > TP1 (workload is decode-dominated)
#
# Key takeaway: There's a trade-off between TPOT and TTFT for configuration
# choices. This motivates PD disaggregation - we need to optimize prefill and
# decode separately.

set -e  # Exit on error

# Configuration
ITL=5000
OTL=250

echo "=========================================="
echo "TP Baselines"
echo "Understanding TTFT vs TPOT trade-offs"
echo "ITL:OTL = ${ITL}:${OTL}"
echo "Testing: TP1, TP2, TP4"
echo "=========================================="
echo ""

# TP=1, 8 replicas
echo "Running TP=1 baseline..."
python launch_gptoss.py --mode collocated --tp 1 --num 8
sleep 30  # Wait for deployment
./run_bm.sh -e baseline_tp1 -t concurrency --itl ${ITL} --otl ${OTL}

echo ""
echo "Waiting 10s before next deployment..."
sleep 10
serve shutdown -y > /dev/null 2>&1
sleep 10

# TP=2, 4 replicas
echo "Running TP=2 baseline..."
python launch_gptoss.py --mode collocated --tp 2 --num 4
sleep 30
./run_bm.sh -e baseline_tp2 -t concurrency --itl ${ITL} --otl ${OTL}

echo ""
echo "Waiting 10s before next deployment..."
sleep 10
serve shutdown -y > /dev/null 2>&1
sleep 10

# TP=4, 2 replicas
echo "Running TP=4 baseline..."
python launch_gptoss.py --mode collocated --tp 4 --num 2
sleep 30
./run_bm.sh -e baseline_tp4 -t concurrency --itl ${ITL} --otl ${OTL}

echo ""
echo "Cleaning up..."
serve shutdown -y > /dev/null 2>&1

echo ""
echo "=========================================="
echo "TP Baseline sweep complete!"
echo "=========================================="
echo ""
echo "Expected observations:"
echo "  - TPOT: TP4 > TP2 > TP1 (decode gets better with higher TP)"
echo "  - TTFT: Non-monotonic (TP2 best at low concurrency, TP1 at high)"
echo "  - Throughput efficiency: TP4 > TP2 > TP1 (decode-dominated)"
echo ""
echo "Visualization command:"
echo "python viz.py --exps \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_8xtp1_baseline_tp1 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_4xtp2_baseline_tp2 \\"
echo "  bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_2xtp4_baseline_tp4"
echo ""
echo "=========================================="


