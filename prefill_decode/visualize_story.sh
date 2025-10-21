#!/bin/bash
#
# Generate visualizations for the three main experiments in the PD disaggregation story
#
# This script creates focused visualizations for each experiment section using
# hand-selected results from bm_results_snapshot/
#
# Usage:
#   ./visualize_story.sh [throughput_metric]
#
# Arguments:
#   throughput_metric: Which throughput to show (output|input|total), default: output
#

set -e

RESULTS_DIR="bm_results_snapshot"
PLOTS_DIR="plots"
THROUGHPUT_METRIC="${1:-output}"

mkdir -p "${PLOTS_DIR}"

echo "=========================================="
echo "Generating PD Disaggregation Story Plots"
echo "=========================================="
echo "Throughput metric: ${THROUGHPUT_METRIC}"
echo ""

#==============================================================================
# Section 1: TP Baselines - Understanding TTFT vs TPOT trade-offs
#==============================================================================

echo "Section 1: TP Baselines"
echo "----------------------------------------"
echo "Comparing TP2, TP4 in collocated mode"
echo ""

python viz.py \
  --exps \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_4xtp2" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_2xtp4" \
  --plot-path "${PLOTS_DIR}/section1_tp_baselines" \
  --latency-mode token \
  --use-normalized \
  --log-latency \
  --log-concurrency \
  --throughput-metric "${THROUGHPUT_METRIC}"

echo "✓ Section 1 complete: ${PLOTS_DIR}/section1_tp_baselines/comprehensive_analysis.png"
echo ""

#==============================================================================
# Section 2a: PD Ratio Exploration - D:TP4 configurations
#==============================================================================

echo "Section 2a: PD Ratio Exploration (D:TP4)"
echo "----------------------------------------"
echo "Comparing different P:D ratios with D:TP4"
echo ""

python viz.py \
  --exps \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_2xtp4" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_1xtp4-1xtp4" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_1xtp2-1xtp4" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_2xtp2-1xtp4" \
  --plot-path "${PLOTS_DIR}/section2a_pd_ratio_dtp4" \
  --latency-mode token \
  --use-normalized \
  --log-latency \
  --log-concurrency \
  --throughput-metric "${THROUGHPUT_METRIC}"

echo "✓ Section 2a complete: ${PLOTS_DIR}/section2a_pd_ratio_dtp4/comprehensive_analysis.png"
echo ""

#==============================================================================
# Section 2b: PD Ratio Exploration - D:TP2 configurations
#==============================================================================

echo "Section 2b: PD Ratio Exploration (D:TP2)"
echo "----------------------------------------"
echo "Comparing different P:D ratios with D:TP2"
echo ""

python viz.py \
  --exps \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_4xtp2" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_1xtp2-1xtp2" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_1xtp2-2xtp2" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_1xtp2-3xtp2" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_2xtp2-1xtp2" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_3xtp2-1xtp2" \
  --plot-path "${PLOTS_DIR}/section2b_pd_ratio_dtp2" \
  --latency-mode token \
  --use-normalized \
  --log-latency \
  --log-concurrency \
  --throughput-metric "${THROUGHPUT_METRIC}"

echo "✓ Section 2b complete: ${PLOTS_DIR}/section2b_pd_ratio_dtp2/comprehensive_analysis.png"
echo ""

#==============================================================================
# Section 3: Network Impact - Pack vs Spread
#==============================================================================

echo "Section 3: Network Impact"
echo "----------------------------------------"
echo "Comparing pack vs spread and network backends"
echo ""

python viz.py \
  --exps \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_2xtp4" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_1xtp4-1xtp4" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_1xtp4-1xtp4-spread-ucx" \
    "${RESULTS_DIR}/gptoss_itl5000_otl250_mixed_1xtp4-1xtp4-spread-libfabric" \
  --plot-path "${PLOTS_DIR}/section3_network_impact" \
  --latency-mode token \
  --use-normalized \
  --log-latency \
  --log-concurrency \
  --throughput-metric "${THROUGHPUT_METRIC}"

echo "✓ Section 3 complete: ${PLOTS_DIR}/section3_network_impact/comprehensive_analysis.png"
echo ""

#==============================================================================
# Summary
#==============================================================================

echo "=========================================="
echo "All visualizations complete!"
echo "=========================================="
echo ""
echo "Generated plots:"
echo "  1. ${PLOTS_DIR}/section1_tp_baselines/comprehensive_analysis.png"
echo "  2. ${PLOTS_DIR}/section2a_pd_ratio_dtp4/comprehensive_analysis.png"
echo "  3. ${PLOTS_DIR}/section2b_pd_ratio_dtp2/comprehensive_analysis.png"
echo "  4. ${PLOTS_DIR}/section3_network_impact/comprehensive_analysis.png"
echo ""

