#!/bin/bash
# Wrapper script for showing and plotting results

# Skip -- if present (used with just)
if [ "$1" == "--" ]; then
    shift
fi

if [ $# -eq 0 ]; then
    # List all experiments
    echo "Available experiments:"
    find bm_results -type d -name "all-parts*" -exec dirname {} \; | sort -u
    exit 0
fi

# Check if last argument is an output file (.png)
OUTPUT_FILE=""
ARGS=()

for arg in "$@"; do
    if [[ "$arg" == *.png ]]; then
        OUTPUT_FILE="$arg"
    else
        # Validate and process experiment paths
        if [[ "$arg" == bm_results/* ]]; then
            # Path already expanded by shell if it contained wildcards
            if [ -d "$arg" ]; then
                ARGS+=("$(basename "$arg")")
            else
                echo "Warning: Experiment directory not found: $arg" >&2
            fi
        else
            echo "Error: Experiment path must start with 'bm_results/'"
            echo "Usage: ./results.sh bm_results/EXP_NAME [OUTPUT.png]"
            echo "       ./results.sh bm_results/rayoss251-x* output.png"
            exit 1
        fi
    fi
done

if [ ${#ARGS[@]} -eq 0 ]; then
    echo "Error: No valid experiments found"
    exit 1
fi

# Show results for each experiment
for exp_base in "${ARGS[@]}"; do
    exp_path="bm_results/$exp_base"
    if [ -d "$exp_path" ]; then
        echo "Results for $exp_path:"
        ALL_PARTS=$(find "$exp_path" -type d -name "all-parts*" | head -1)
        if [ -n "$ALL_PARTS" ]; then
            ls -lh "$ALL_PARTS" 2>/dev/null | tail -n +2
        fi
        echo ""
    fi
done

# Generate plot
if [ -n "$OUTPUT_FILE" ]; then
    PLOT_FILE="$OUTPUT_FILE"
else
    if [ ${#ARGS[@]} -eq 1 ]; then
        PLOT_FILE="bm_results/${ARGS[0]}_plot.png"
    else
        PLOT_FILE="bm_results/compare_$(IFS='_'; echo "${ARGS[*]}").png"
    fi
fi

python3 plot_results.py "${ARGS[@]}" --output "$PLOT_FILE"

