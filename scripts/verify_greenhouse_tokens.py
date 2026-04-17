"""Verify which companies have valid Greenhouse job boards by hitting the API."""
import asyncio
import aiohttp

# Large candidate list: known H-1B sponsoring tech companies + likely Greenhouse tokens
CANDIDATES = [
    # === BIG TECH (confirmed H-1B sponsors) ===
    ("amazon", "Amazon"), ("google", "Google"), ("microsoft", "Microsoft"),
    ("meta", "Meta"), ("apple", "Apple"), ("netflix", "Netflix"),
    ("nvidia", "NVIDIA"), ("tesla", "Tesla"), ("uber", "Uber"),
    ("lyft", "Lyft"), ("airbnb", "Airbnb"), ("doordash", "DoorDash"),
    ("spotify", "Spotify"), ("snap", "Snap"), ("pinterest", "Pinterest"),
    ("dropbox", "Dropbox"), ("salesforce", "Salesforce"), ("oracle", "Oracle"),
    ("intel", "Intel"), ("amd", "AMD"), ("qualcomm", "Qualcomm"),
    ("cisco", "Cisco"), ("ibm", "IBM"), ("vmware", "VMware"),
    ("palantir", "Palantir"), ("snowflake", "Snowflake"),
    ("databricks", "Databricks"), ("splunk", "Splunk"),

    # === AI / ML COMPANIES ===
    ("anthropic", "Anthropic"), ("openai", "OpenAI"),
    ("huggingface", "Hugging Face"), ("cohere", "Cohere"),
    ("scale", "Scale AI"), ("anyscale", "Anyscale"),
    ("deepmind", "DeepMind"), ("stability", "Stability AI"),
    ("stabilityai", "Stability AI"), ("mistral", "Mistral AI"),
    ("mistrali", "Mistral AI"), ("perplexityai", "Perplexity AI"),
    ("perplexity", "Perplexity"), ("adept", "Adept AI"),
    ("adeptailabs", "Adept AI"), ("inflection", "Inflection AI"),
    ("characterai", "Character AI"), ("runwayml", "Runway"),
    ("runway", "Runway"), ("replicatehq", "Replicate"),
    ("replicate", "Replicate"), ("wandb", "Weights & Biases"),
    ("labelbox", "Labelbox"), ("tecton", "Tecton"),
    ("mosaicml", "MosaicML"), ("together", "Together AI"),
    ("togetherai", "Together AI"), ("modal", "Modal"),
    ("modallabs", "Modal"),

    # === CLOUD / INFRASTRUCTURE ===
    ("cloudflare", "Cloudflare"), ("datadog", "Datadog"),
    ("hashicorp", "HashiCorp"), ("elastic", "Elastic"),
    ("grafanalabs", "Grafana Labs"), ("confluent", "Confluent"),
    ("mongodb", "MongoDB"), ("cockroachlabs", "Cockroach Labs"),
    ("planetscale", "PlanetScale"), ("vercel", "Vercel"),
    ("netlify", "Netlify"), ("digitalocean", "DigitalOcean"),
    ("fly", "Fly.io"), ("render", "Render"), ("supabase", "Supabase"),
    ("neon", "Neon"), ("pulumi", "Pulumi"), ("temporal", "Temporal"),
    ("temporalio", "Temporal"), ("clickhouse", "ClickHouse"),
    ("timescale", "Timescale"), ("coreweave", "CoreWeave"),
    ("lambdalabs", "Lambda Labs"), ("aiven", "Aiven"),
    ("redpandadata", "Redpanda"), ("redpanda", "Redpanda"),
    ("starburst", "Starburst"), ("starburstdata", "Starburst"),
    ("fivetran", "Fivetran"), ("dbtlabs", "dbt Labs"),
    ("airbyte", "Airbyte"), ("prefect", "Prefect"),

    # === SECURITY / CYBERSECURITY ===
    ("crowdstrike", "CrowdStrike"), ("paloaltonetworks", "Palo Alto Networks"),
    ("snyk", "Snyk"), ("lacework", "Lacework"), ("sentinelone", "SentinelOne"),
    ("zscaler", "Zscaler"), ("fortinet", "Fortinet"),
    ("1password", "1Password"), ("okta", "Okta"), ("wiz", "Wiz"),
    ("wizinc", "Wiz"), ("orcasecurity", "Orca Security"),
    ("chainguard", "Chainguard"), ("aquasecurity", "Aqua Security"),
    ("sysdig", "Sysdig"), ("abnormalsecurity", "Abnormal Security"),
    ("arcticwolfnetworks", "Arctic Wolf"), ("huntress", "Huntress"),
    ("recordedfuture", "Recorded Future"), ("bitwarden", "Bitwarden"),
    ("axonius", "Axonius"), ("armis", "Armis"),
    ("isovalent", "Isovalent"), ("tailscale", "Tailscale"),
    ("vanta", "Vanta"), ("drata", "Drata"), ("semgrep", "Semgrep"),

    # === DEVOPS / PLATFORM ===
    ("gitlab", "GitLab"), ("github", "GitHub"), ("circleci", "CircleCI"),
    ("harness", "Harness"), ("harnessio", "Harness"),
    ("launchdarkly", "LaunchDarkly"), ("newrelic", "New Relic"),
    ("pagerduty", "PagerDuty"), ("firehydrant", "FireHydrant"),
    ("env0", "env0"), ("spacelift", "Spacelift"), ("buildkite", "Buildkite"),

    # === FINTECH / SaaS (known H-1B sponsors) ===
    ("stripe", "Stripe"), ("plaid", "Plaid"), ("brex", "Brex"),
    ("ramp", "Ramp"), ("robinhood", "Robinhood"), ("coinbase", "Coinbase"),
    ("ripple", "Ripple"), ("figma", "Figma"), ("notion", "Notion"),
    ("discord", "Discord"), ("reddit", "Reddit"), ("twitch", "Twitch"),
    ("gusto", "Gusto"), ("squarespace", "Squarespace"),
    ("shopify", "Shopify"), ("instacart", "Instacart"),
    ("grammarly", "Grammarly"), ("duolingo", "Duolingo"),
    ("hubspot", "HubSpot"), ("twilio", "Twilio"), ("block", "Block"),
    ("chime", "Chime"), ("marqeta", "Marqeta"),
    ("nerdwallet", "NerdWallet"), ("sofi", "SoFi"),

    # === MORE TECH COMPANIES ===
    ("flexport", "Flexport"), ("airtable", "Airtable"),
    ("asana", "Asana"), ("canva", "Canva"), ("miro", "Miro"),
    ("webflow", "Webflow"), ("retool", "Retool"), ("linear", "Linear"),
    ("postman", "Postman"), ("snorkelai", "Snorkel AI"),
    ("navan", "Navan"), ("rippling", "Rippling"), ("lattice", "Lattice"),
    ("benchling", "Benchling"), ("samsara", "Samsara"), ("toast", "Toast"),
    ("zip", "Zip"), ("relativity", "Relativity"),

    # === ADDITIONAL KNOWN GREENHOUSE USERS ===
    ("watershed", "Watershed"), ("loom", "Loom"), ("calm", "Calm"),
    ("masterclass", "MasterClass"), ("roblox", "Roblox"),
    ("niantic", "Niantic"), ("mapbox", "Mapbox"),
    ("contentful", "Contentful"), ("segment", "Segment"),
    ("launchdarkly", "LaunchDarkly"), ("cockroachlabs", "Cockroach Labs"),
    ("sourcegraph", "Sourcegraph"), ("materialize", "Materialize"),
    ("materializeinc", "Materialize"), ("yugabyte", "YugaByte"),
    ("timescale", "Timescale"), ("hasura", "Hasura"),
    ("apollographql", "Apollo GraphQL"), ("kong", "Kong"),
    ("konghq", "Kong"), ("solo", "Solo.io"), ("soloio", "Solo.io"),
    ("rancher", "Rancher"), ("teleport", "Teleport"),
    ("goteleport", "Teleport"), ("tailscale", "Tailscale"),
    ("ngrok", "ngrok"), ("zeronetworks", "Zero Networks"),
    ("fastly", "Fastly"), ("fly", "Fly.io"),
]

API = "https://boards-api.greenhouse.io/v1/boards"


async def check_token(session, token, name):
    url = f"{API}/{token}/jobs"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                data = await resp.json()
                count = len(data.get("jobs", []))
                return (token, name, count)
    except Exception:
        pass
    return None


async def main():
    # Deduplicate by token
    seen = set()
    unique = []
    for token, name in CANDIDATES:
        if token not in seen:
            seen.add(token)
            unique.append((token, name))

    print(f"Testing {len(unique)} candidate tokens against Greenhouse API...")
    print()

    async with aiohttp.ClientSession() as session:
        tasks = [check_token(session, t, n) for t, n in unique]
        results = await asyncio.gather(*tasks)

    valid = [r for r in results if r]
    valid.sort(key=lambda x: x[2], reverse=True)

    print(f"VALID Greenhouse boards: {len(valid)} out of {len(unique)} tested")
    print()
    print(f"{'Company':<30} {'Token':<25} {'Jobs':>6}")
    print("-" * 63)
    for token, name, count in valid:
        print(f"{name:<30} {token:<25} {count:>6}")

    # Output YAML
    print("\n\n# === YAML for target_companies.yaml ===\n")
    print("greenhouse:")
    for token, name, count in valid:
        if count > 0:
            print(f"  - token: {token}")
            print(f"    name: {name}")


if __name__ == "__main__":
    asyncio.run(main())
