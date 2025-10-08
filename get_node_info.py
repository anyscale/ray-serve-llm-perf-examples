from ray.serve._private.test_utils import get_application_urls


base_urls = get_application_urls(use_localhost=False, app_name="default")
base_urls_str = [f'"{url}"' for url in base_urls]
print(f"({' '.join(base_urls_str)})")