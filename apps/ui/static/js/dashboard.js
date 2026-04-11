// LV_DCP dashboard frontend — D3 force graph + sparklines.
// Loaded from every template via base.html.j2. Safe to include on pages
// that lack the graph or sparkline containers — each render function
// exits early if its target DOM is absent.
(function () {
    'use strict';

    function renderGraph() {
        var container = document.getElementById('dep-graph');
        if (!container) return;
        var slug = container.dataset.projectSlug;
        var canvas = document.getElementById('dep-graph-canvas');
        var info = document.getElementById('dep-graph-info');
        var ctx = canvas.getContext('2d');

        function resize() {
            canvas.width = container.clientWidth;
            canvas.height = container.clientHeight;
        }
        resize();
        window.addEventListener('resize', resize);

        d3.json('/api/project/' + slug + '/graph.json').then(function (data) {
            if (!data || !data.nodes || data.nodes.length === 0) {
                info.textContent = 'No graph data';
                return;
            }

            var maxVisible = 200;
            var totalNodes = data.nodes.length;
            var nodes = data.nodes.slice(0, maxVisible).map(function (n) {
                return Object.assign({}, n);
            });
            var nodeIds = new Set(nodes.map(function (n) { return n.id; }));
            var links = data.edges
                .filter(function (e) { return nodeIds.has(e.src) && nodeIds.has(e.dst); })
                .map(function (e) { return { source: e.src, target: e.dst }; });

            info.textContent = nodes.length + ' nodes, ' + links.length + ' edges' +
                (totalNodes > maxVisible ? ' (+' + (totalNodes - maxVisible) + ' hidden)' : '');

            var simulation = d3.forceSimulation(nodes)
                .force('link', d3.forceLink(links).id(function (d) { return d.id; }).distance(50))
                .force('charge', d3.forceManyBody().strength(-30))
                .force('center', d3.forceCenter(canvas.width / 2, canvas.height / 2))
                .alphaDecay(0.02)
                .on('tick', draw);

            var roleColor = {
                code: '#2a5caa',
                test: '#2e7d32',
                config: '#f57c00',
                docs: '#888888'
            };

            function draw() {
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.strokeStyle = '#cccccc';
                ctx.lineWidth = 0.5;
                ctx.beginPath();
                links.forEach(function (l) {
                    ctx.moveTo(l.source.x, l.source.y);
                    ctx.lineTo(l.target.x, l.target.y);
                });
                ctx.stroke();

                nodes.forEach(function (n) {
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, 3, 0, 2 * Math.PI);
                    ctx.fillStyle = roleColor[n.role] || '#666666';
                    ctx.fill();
                });
            }
        }).catch(function (err) {
            info.textContent = 'Error loading graph: ' + err.message;
        });
    }

    function renderSparklines() {
        var row = document.querySelector('.sparkline-row');
        if (!row) return;
        var slug = row.dataset.projectSlug;

        d3.json('/api/project/' + slug + '/sparklines.json').then(function (series) {
            if (!Array.isArray(series)) return;
            series.forEach(function (s) {
                var item = row.querySelector('[data-metric="' + s.metric + '"]');
                if (!item) return;
                var svg = d3.select(item).select('svg.sparkline');
                var width = parseInt(svg.attr('width'), 10);
                var height = parseInt(svg.attr('height'), 10);
                var buckets = s.buckets || [];
                if (buckets.length === 0) return;

                var x = d3.scaleLinear()
                    .domain([0, buckets.length - 1])
                    .range([2, width - 2]);
                var y = d3.scaleLinear()
                    .domain([0, Math.max(1, d3.max(buckets) || 1)])
                    .range([height - 2, 2]);

                var line = d3.line()
                    .x(function (_, i) { return x(i); })
                    .y(function (d) { return y(d); })
                    .curve(d3.curveMonotoneX);

                svg.selectAll('*').remove();
                svg.append('path')
                    .datum(buckets)
                    .attr('fill', 'none')
                    .attr('stroke', '#2a5caa')
                    .attr('stroke-width', 1.5)
                    .attr('d', line);
            });
        }).catch(function () {
            // Silent — sparklines are non-critical; absence is fine.
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        renderGraph();
        renderSparklines();
    });
})();
