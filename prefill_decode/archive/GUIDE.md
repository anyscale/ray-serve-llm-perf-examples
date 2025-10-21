Related docs:
- user guide: https://docs.ray.io/en/master/serve/llm/user-guides/prefill-decode.html
- Architecture: https://docs.ray.io/en/master/serve/llm/architecture/serving-patterns/prefill-decode.html

High level sketch: 

In this repo, we would like to show the benefit of prefill decode dissagregration on an example workload on an example model (gpt-oss-120b) on an example hardware setup (2x8xH100 nodes with EFA on AWS: 2xp5.48xlarge) using ray serve llm's PD support. The idea is to create an example that can be referenced for testing similar setup or be used to guide testing on different setups (different workload, different model, different hardware).

We want to make sure the results are reproducible under the same conditions. So we include the exact command or set of commands that were used to generate a set of benchmarking artifacts. 

We fix our setup to something that we found to be working at the time of testin this:

```
vllm==0.11.0
nixl==0.6.1 (install from source with UCX commit xyz (to be released for 1.20.0))
flashinfer-python==0.2.14.post1
ray nightly (to be released on 2.51.0) <commit number for this>
```

Some notes on these dependencies
- vllm 0.11.0 was the latest released version at the time of writing this repository. We encourage users to try the latest vllm that is supported with ray. Sometimes newer version of vllm might introduce API incompatibility that needs adjustment on ray serve LLM APIs. 
- Nixl 0.6.1 -- This released version is the first version that supported libfabric plugin. We could not get this plugin to work properly at the time of writing this repo, due to issues reported here: https://github.com/vllm-project/vllm/issues/27055. What we found to work on EFA was building NIXL against UCX the above commit (past the UCX 1.19.0 released version which nixl 0.6.1 comes with). This UCX supports SRD backend which gives us good and correct speed on EFA machines. See  /home/ray/default/ray-serve-pd-example/debug/build_nixl_ucx_efa.sh fo installation procedure. 

We created a `launch_gptoss.py` script that will help us launch the server under different target benchmarking settings:

- We would like to be able to compare collocated and pd setups under different configurations (number of replicas and parallelism)
- For PD setups we would like to compare different placement options to stress-test impact of inter-node vs. intra-node communication. 

We have a ray cluster of one head node and two p5.48xlarge worker nodes. `--collocated` will do a aggregated deployment. `--pd-pack` make sure the P and D instances are scheduled on the same node (assuming availablity of resources) and `--pd-spread` makes sure that P instances are on 1 node and D instances are on a different node excersising the cross node communication. 


Current vllm version does not allow settings where P has more TP degree than D. This will change in future versions. <find the corresponding PR / issue to link here>


We also created `run_bm.sh` which runs constant concurrency / constant request rate sweeps against a target deployment. 
You can also configure the benchmark to do `mixed (ITL:OTL)`, `prefill-only (ITL:1)`, and `decode-only (1:OTL)` to get breakdowns of different phases.

Notes on decode only: 
- Modeling decode-only via 1:OTL output is not realistic ecause it doesn't model the impact of input token lengh on generation speed.
- Proper way of benchmarking for decode only is supposed be supported in this PR: https://github.com/vllm-project/vllm/pull/25986/



We can use `viz.py` to plot the visualizations. Example:
```bash
python viz.py --exps bm_results/exp1 bm_results/exp2 --use-normalized
```


## Metrics for assement

Metrics that we care about: 
TTFT - Latency
TPOT - Latency
Throughput - Efficiency / token cost
Throughput vs. interactivity
Tput: output/input/total – all show the same exact trends, because they have the exact same principal components. They are all computed based on total tokens / duration, and the only parameter that changes across benchmarks is duration. 
For interactivity:
- Option 1: tpot – only captures decode latency
- Option 2: ttft – only captures prefill latency
- Option 3: (ttft + 16 tpot) – chunks / s / usr – first chunk interactivity – captures both decode and prefill latency 
We chose Option 1: because that’s what everyone shows, mostly in the form of interactivity (1000/tpot which is measured by tokens / s / usr). 
If you care about a different SLA you should change the X-axis to that latency metric so that you can pick the optimal configuration given that particular SLA. 

In the rest of this article we directly use TPOT for the x-axis and normalized per node throughput on the y-axis.

**viz.py high-level documentation:**

The visualization tool supports different latency modes:
- `--latency-mode token`: Uses TPOT (Time per Output Token)
- `--latency-mode first_token`: Uses TTFT (Time to First Token)
- `--latency-mode chunk`: Uses chunk latency formula: `(chunk_size - 1) * TPOT + TTFT`
- `--use-interactivity`: Uses interactivity metric (1000/TPOT) instead of latency

All throughput metrics can be normalized per-node using `--use-normalized` for fair comparison across different GPU counts. 


## high level points we want to make / learnings:

1. 
The most important part of the trick in PD setup is setting the P and D ratios correctly. Setting it wrong, might result in not seeing the benefits of PD for your workload at all. Examples:

For P: TP2 and D: TP2 (in comparison with TP2 collocated on ITL/OTL 5000:250 workload); we can see that, 2:1, 3:1 ratios are strictly dominated by collocated (red and blue are dominated by brown), but as we increase D / P ratio to 1:1, 1:2, 1:3 we see the benefits. In this particular workload, higher D count is better (despite the workload having an ITL/OTL ratio of 20!!) 

Another important observation: in low tpot - low throughput regime, the optimal ratio is 1:3 (purple line). As we go to a higher throughput range of 50k+, ratio of 1:2 (green line) becomes more optimal reaching 12.7 RPS and at 65k+, ratio of 1:1 (orange line) reaches 13.1 RPS. At higher throughput of 70k+ collocated setup of 4xTP2 outcompetes these PD setups giving a better trade off for latency-throughput.

For P: TP1, D: TP2 (in comparison with TP2 collocated on ITL/OTL 5000:250 workload). We see a similar trend: in low throughput / low latency regime, 1:2 ratio (green) is better, in mid throughput/mid latency regime 1:1 ratio (orange) is better, in higher than 60k in PD setups, 2:1 ratio beats 1:1, but it doesn’t beat 4xTP2 anymore. 

<include results for both>


These two examples show that: 

PD can beat a collocated setup on efficiency (throughput / latency trade off) under certain conditions depending on target latency SLA. 
How important it is to dynamically adjust the number of P and D replicas to maintain the optimal ratio for a given SLA that maximizes the efficiency. 




2. 
Another important trick about PD is figuring out the P and D configurations so that we can ratio them properly later. Experiments:
First, optimizing for P innately degrades D and vice versa. This is why you need PD in the first place. Decode (TPOT) gets better at higher TP degrees when we sweep TP from 1 to 8 maintaining the total GPU count (i.e. TP8 > TP4 > TP2 > TP1). However, prefill (TTFT) doesn’t follow this rule. In fact, TP2 is optimal on some concurrencies and TP1 becomes optimal for some other higher concurrencies, while TP4 maintains a balance on high and low concurrencies.. Now given these the right question to ask is what do we pick for P and what do we pick for D. Should we pick the best setting for P (TP2) and the best setting for D (TP4 assuming we want to do single node PD but TP8 if we are ok with cross node)? 

<results from collocated settings>

3. 
Another observation: In terms of efficiency-latency trade off for this particular workload we can see that TP8 > TP4 > TP2 > TP1. This measurement tells the efficiency for this workload is mostly determined by the efficiency in decode assuming P can push enough traffic into D. 

Another note about Nixl connector: P:TPN, D:TPM where N > M is not allowed in the current implementation. This is because NIXL assumes a one to many transfer between P and D and not many to one.
We sweep through TP4, TP2, TP1 combos of P and D and different ratios subject to maintaining single node setting and we can compare them on efficiency-latency trade off. 
We can see that the non-trivial P:TP4, D:TP4 with 1:1 ratio gives the best single node efficiency - latency trade off. So one should sweep these different settings and measure the outcome. 


4. 
Impact of network layer on PD perf: Let’s compare PD scenarios, where we can physically place P and D on single or multi-nodes and measure the impact of the transport layer on the overall perf. 
If NIXL does not find the right transport layer you can kill performance. Figure below shows the case where for multi-node the ucx backend uses udverb/rdma instead of EFA. You can see how bad the performance gets. You need to make sure nixl can exhaust the throughput of your network bw. For this I have created a small ray-based script that tests the transport layer.

Setting NIXL_LOGGING_LEVEL=DEBUG severely impacts the performance. 
The first blue line has DEBUG on, but then if we turn debug off, both spread and pack deployments through libfabric show a significant improvement over the blue line

<results>

For debugging the multi-node setup we used /home/ray/default/ray-serve-pd-example/debug/test_nixl_connector_ray.py which immitates what the kv cache transfer does through nixl. you can use that to measure the effecitve bandwidth at different kv cache sizes. You should read the readme_nixl_ray.md to understand how it works and see examples of what we have tried. 




Disclaimer: Most of this repository is vibe-coded with Claude 4.5. 



# Revised story:

1. Get the TP baselines first; we would see that: 
    - for TPOT: TP4 > TP2 > TP1
    - for TTFT: in low concurrency TP2 > TP4 > TP1, in high concurrency, TP1 > TP2 > TP4.

This basically tell us that there is a trade off between TPOT and TTFT for configuration choices; one of the reasons motivating PD. In terms of throughput efficiency, TP4 > TP2 > TP1, telling us the workload is decode dominated. The amount of time spent for decode is higher compared to prefill. So we need to put more resources towards decode to improve efficiency. 

2. For each decode case of TP4, TP2, we try TP4, TP2, TP1 with different ratios and we then compare from different angles:


Np-Md

d:tp4
    tp4 - tp4
        1tp4 - 1tp4

    tp2 - tp4
        1tp2 - 1tp4
        2tp2 - 1tp4

    tp1 - 1tp4
        1tp1 - 1tp4
        2tp1 - 1tp4
        3tp1 - 1tp4
        4tp1 - 1tp4

d: tp2
    tp4 - tp2 x not allowed by vLLM yet!
    tp2 - tp2
        1tp2 - 1tp2
        2tp2 - 1tp2
        3tp2 - 1tp2
        1tp2 - 2tp2
        1tp2 - 3tp2
    
    tp1 - tp2
        1tp1 - 1tp2
        2tp1 - 1tp2
        4tp1 - 1tp2
        1tp1 - 2tp2
        2tp1 - 3tp2

Takeaways:

* Ratio is very important, by zooming in on different ratios for tp2 - tp2 cases and emphasis on the need to dynamically adjust p and d as traffic scales
* PD can beat collocated in token efficiency, zooming in on tp4 - tp4

3. Cross node vs. Inter node

We compare spread vs. pack placement on tp4-tp4 case. In one experiment, we place P and D with TP4 on the same node. In this case, the UCX backend will use cuda_ipc. In another experiment, we place P and D on different nodes. In this case, the UCX backend should use the 

If network bw is good, we'll see basically identical results, but if bw is bad we'll see bad results (using UCX_TLS we can control the transport layer). So we could do `UCX_TLS="tcp"` to force using tcp which is bad (this could happen if the RDMA backend is not supported by nixl, etc). You can see the delta under such scenarios.

compare: tp4-tp4-packed vs. tp4-tp4-spread (srd) vs. tp4-tp4-spread (tcp)

We can use the nixl-ray benchmark to validate the tranfer bandwidth. 



In debugging, let's include these stories:

- Inspecting bandwidth with ray-nixl benchmark -- basically tells you that under inter / intra node settings what bw can you obtain for kv-cache transfer
- Using `--verbose`, this can tell you what transport backend you are using (CUDA_IPC, TCP, SDR, etc)
- LIBFABRIC does not work as of writing this doc issues tracked in the linked issue.