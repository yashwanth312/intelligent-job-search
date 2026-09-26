---
id: netcore
name: "NetCore"
tagline: "Enterprise network services as code — DNS, DHCP, firewall, VPN, routing, PKI"
role_families: [network, sysadmin, infra, security]
skills:
  core: [networking, dns_dhcp, firewall_vpn, routing_switching, load_balancing]
  supporting: [pki_tls, linux, zero_trust]
  touch: [ansible, python, vpc_networking_cloud]
est_days: 3
lab_cost: "$0 — GNS3/Containerlab, VyOS/FRRouting, pfSense/OPNsense VMs; optional $5/mo VPS for site-to-site VPN"
---

# NetCore — Enterprise Network Services as Code

## Problem
Network changes in smaller orgs are still done by hand in a firewall GUI or a router CLI.
There's no source of truth, no review, and no fast rollback, so a single typo in a firewall
rule or DNS record takes production down. Branch and remote access VPNs are configured
once and never documented.

## Why it matters (impact)
- Network config in Git = peer review, history, and one-command rollback.
- Automated validation (reachability + policy tests) before changes go live prevents
  change-induced outages — the #1 cause of network incidents.
- Segmentation (VLANs + least-privilege firewall policy) shrinks blast radius.

## Approach
1. Containerlab/GNS3 topology: 2 sites (HQ + branch), core router pair, access switches.
2. Routing: OSPF inside each site, BGP between sites/ISP simulation (FRRouting/VyOS),
   VLANs for users/servers/mgmt/guest.
3. Services: BIND/Unbound DNS (split-horizon), Kea/ISC DHCP with reservations,
   HAProxy/NGINX load balancer with health checks in front of 2 web servers.
4. Security: OPNsense firewall with zone-based policy, WireGuard site-to-site + remote
   access VPN, internal CA (step-ca) issuing TLS certs with auto-renewal.
5. Everything rendered from a YAML source of truth by Ansible/Jinja2
   (NetBox optional as SoT).
6. CI validation: `batfish` or pytest reachability checks (ping/traceroute/port tests)
   run against the lab before config is applied; drift detection nightly.

## Architecture
```
YAML source of truth ─> Ansible/Jinja2 ─> routers (OSPF/BGP) · switches (VLANs)
                               │         ─> OPNsense (zones, WireGuard) · DNS/DHCP · HAProxy
                               └─> CI: batfish/pytest reachability + policy tests ─> apply / rollback
```

## Interview-ready core (days 1–2)
Two-site lab with VLANs, OSPF + BGP, DNS/DHCP, firewall zones and a WireGuard tunnel,
all generated from YAML with Ansible.

## Full build plan
| Day | Deliverable |
|---|---|
| 1 | Topology, VLANs, OSPF/BGP, DNS/DHCP |
| 2 | Firewall zones, WireGuard S2S + remote access, HAProxy, internal CA |
| 3 | Ansible SoT rendering, CI reachability/policy tests, drift detection |

## Target metrics (measure; replace with actuals)
- 2 sites, 5 VLANs, 40+ firewall rules, all generated from one YAML SoT.
- Full-lab config push < 2 min; rollback < 1 min.
- 30+ automated reachability/policy tests gating every change; BGP failover < 5 s.

## Draft resume bullets
- Designed a two-site enterprise network lab with VLAN segmentation, OSPF and BGP routing, split-horizon DNS, DHCP and HAProxy load balancing, generated entirely from a YAML source of truth with Ansible.
- Implemented zone-based firewall policy, WireGuard site-to-site and remote-access VPN, and an internal certificate authority with automated TLS renewal.
- Gated every network change behind 30+ automated reachability and policy tests, enabling one-command rollback and nightly configuration drift detection.

## Likely interview questions
- Walk through a packet from a laptop to a website (ARP, DHCP, DNS, routing, NAT, TLS).
- OSPF vs BGP; when BGP is used inside an enterprise.
- Stateful vs stateless firewall; how you'd troubleshoot "can't reach server".
- How DNS resolution fails and how you'd debug it (`dig +trace`).
