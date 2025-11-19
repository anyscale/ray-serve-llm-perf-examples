# Cluster Setup

## Starting the Ray Cluster

**On the head node:**
```bash
ray start --head
```

**On each of the prefill nodes (8xH100):**
```bash
ray start --address='<head_ip>:6379' --resources='{"prefill": 8}'
```

**On each of the decode nodes (8xH100):**
```bash
ray start --address='<head_ip>:6379' --resources='{"decode": 8}'
```

Replace `<head_ip>` with your actual head node IP address, or specify these custom resources in a KubeRay .yaml.

