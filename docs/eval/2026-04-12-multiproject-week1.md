# Multi-project Eval — week1

## Per-project results

### Project_Large

| id | recall@5 | missed |
|---|---|---|
| tc01-telegram-client-en | 1.00 | — |
| tc02-telegram-scraping-en | 0.00 | src/telegram/client.py, src/telegram/client_pool.py |
| tc03-add-source-en | 0.00 | src/telegram/client.py, src/telegram/client_pool.py |
| tc04-keyword-analytics | 0.00 | src/services/keyword_research_service.py |
| tc05-web-app-routes | 1.00 | — |

**Average recall@5: 0.400**

### Project_Medium_A

| id | recall@5 | missed |
|---|---|---|
| tp01-vpn-handlers | 0.50 | bot/handlers/admin/assign_vpn.py |
| tp02-vpn-model | 1.00 | — |

**Average recall@5: 0.750**

### Project_Medium_B

| id | recall@5 | missed |
|---|---|---|
| tr01-admin-commands | 1.00 | — |

**Average recall@5: 1.000**

### Project_Small

| id | recall@5 | missed |
|---|---|---|
| lp01-content-api | 1.00 | — |

**Average recall@5: 1.000**

## Global average recall@5: 0.611
