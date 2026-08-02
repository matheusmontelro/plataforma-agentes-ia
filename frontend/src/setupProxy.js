const { createProxyMiddleware } = require('http-proxy-middleware');

module.exports = function (app) {
    app.use(
        ['/api', '/webhook', '/media-sources', '/auth', '/health'],
        createProxyMiddleware({
            target: 'http://localhost:8002',
            changeOrigin: true,
        })
    );
};
