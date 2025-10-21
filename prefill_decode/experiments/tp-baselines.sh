#!/bin/bash
# TP Baselines - Understanding TTFT vs TPOT Trade-offs
#
# This experiment establishes collocated baselines to understand:
# - TPOT (decode performance): TP4 > TP2
# - TTFT (prefill performance): TP2 better at low concurrency, TP4 at high concurrency
# - Throughput efficiency: TP4 > TP2 (workload is decode-dominated)
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
echo "Testing: TP2, TP4"
echo "=========================================="
echo ""

# TP=2, 4 replicas
echo "Running TP=2 baseline..."
python launch_gptoss.py --mode collocated --tp 2 --num 4
sleep 30
./run_bm.sh -e baseline_4xtp2 -t concurrency --itl ${ITL} --otl ${OTL}

echo ""
echo "Waiting 10s before next deployment..."
sleep 10
serve shutdown -y > /dev/null 2>&1
sleep 10

# TP=4, 2 replicas
echo "Running TP=4 baseline..."
python launch_gptoss.py --mode collocated --tp 4 --num 2
sleep 30
./run_bm.sh -e baseline_2xtp4 -t concurrency --itl ${ITL} --otl ${OTL}

echo ""
echo "Cleaning up..."
serve shutdown -y > /dev/null 2>&1

echo ""
echo "=========================================="
echo "TP Baseline sweep complete!"
echo "=========================================="
echo ""
echo "Expected observations:"
echo "  - TPOT: TP4 > TP2 (decode gets better with higher TP)"
echo "  - TTFT: TP2 better than TP4"
echo "  - Throughput efficiency: TP4 > TP2 (decode-dominated)"
echo ""
echo "Generating visualization..."
echo ""

python viz.py \
  --exps \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_baseline_4xtp2 \
    bm_results/gptoss_itl${ITL}_otl${OTL}_mixed_baseline_2xtp4 \
  --plot-path plots/tp_baselines \
  --latency-mode token \
  --use-normalized \
  --log-latency \
  --log-concurrency \
  --throughput-metric output

echo ""
echo "Visualization saved to: ../plots/tp_baselines/comprehensive_analysis.png"
echo ""
echo "=========================================="


