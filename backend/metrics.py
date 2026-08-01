from prometheus_client import Counter, Histogram

REQUEST_COUNT = Counter(
    'saas_business_request_count',
    'Contagem de requisições recebidas por endpoint',
    ['method', 'endpoint']
)

REQUEST_LATENCY = Histogram(
    'saas_business_request_latency_seconds',
    'Tempo de resposta por endpoint',
    ['method', 'endpoint']
)
