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

        var tooltip = document.createElement('div');
        tooltip.style.cssText = 'position:absolute;padding:4px 8px;background:#1a1a2e;color:#eee;' +
            'border-radius:4px;font-size:12px;pointer-events:none;display:none;white-space:nowrap;z-index:10';
        container.style.position = 'relative';
        container.appendChild(tooltip);

        var hoveredNode = null;

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

            var degree = {};
            links.forEach(function (l) {
                var s = typeof l.source === 'object' ? l.source.id : l.source;
                var t = typeof l.target === 'object' ? l.target.id : l.target;
                degree[s] = (degree[s] || 0) + 1;
                degree[t] = (degree[t] || 0) + 1;
            });
            var maxDeg = Math.max(1, d3.max(Object.values(degree)) || 1);
            nodes.forEach(function (n) {
                n.degree = degree[n.id] || 0;
                n.radius = 2 + 6 * Math.sqrt(n.degree / maxDeg);
            });

            var neighbors = {};
            links.forEach(function (l) {
                var s = typeof l.source === 'object' ? l.source.id : l.source;
                var t = typeof l.target === 'object' ? l.target.id : l.target;
                if (!neighbors[s]) neighbors[s] = new Set();
                if (!neighbors[t]) neighbors[t] = new Set();
                neighbors[s].add(t);
                neighbors[t].add(s);
            });

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
                var hId = hoveredNode ? hoveredNode.id : null;
                var hNeighbors = hId && neighbors[hId] ? neighbors[hId] : null;

                links.forEach(function (l) {
                    var sId = l.source.id, tId = l.target.id;
                    var active = hId && (sId === hId || tId === hId);
                    ctx.strokeStyle = active ? '#e74c3c' : (hId ? 'rgba(200,200,200,0.15)' : '#cccccc');
                    ctx.lineWidth = active ? 1.5 : 0.5;
                    ctx.beginPath();
                    ctx.moveTo(l.source.x, l.source.y);
                    ctx.lineTo(l.target.x, l.target.y);
                    ctx.stroke();
                });

                nodes.forEach(function (n) {
                    var isHovered = hId === n.id;
                    var isNeighbor = hNeighbors && hNeighbors.has(n.id);
                    var dimmed = hId && !isHovered && !isNeighbor;
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, isHovered ? n.radius + 2 : n.radius, 0, 2 * Math.PI);
                    var base = roleColor[n.role] || '#666666';
                    ctx.fillStyle = dimmed ? 'rgba(180,180,180,0.3)' : base;
                    ctx.fill();
                    if (isHovered) {
                        ctx.strokeStyle = '#e74c3c';
                        ctx.lineWidth = 2;
                        ctx.stroke();
                    }
                });
            }

            canvas.addEventListener('mousemove', function (e) {
                var rect = canvas.getBoundingClientRect();
                var mx = e.clientX - rect.left;
                var my = e.clientY - rect.top;
                var found = null;
                for (var i = nodes.length - 1; i >= 0; i--) {
                    var n = nodes[i];
                    var dx = mx - n.x, dy = my - n.y;
                    if (dx * dx + dy * dy < (n.radius + 3) * (n.radius + 3)) {
                        found = n;
                        break;
                    }
                }
                if (found !== hoveredNode) {
                    hoveredNode = found;
                    if (found) {
                        var label = found.id + ' (' + found.degree + ' connections)';
                        tooltip.textContent = label;
                        tooltip.style.display = 'block';
                        canvas.style.cursor = 'pointer';
                    } else {
                        tooltip.style.display = 'none';
                        canvas.style.cursor = 'default';
                    }
                    draw();
                }
                if (found) {
                    tooltip.style.left = (mx + 12) + 'px';
                    tooltip.style.top = (my - 8) + 'px';
                }
            });

            canvas.addEventListener('mouseleave', function () {
                hoveredNode = null;
                tooltip.style.display = 'none';
                canvas.style.cursor = 'default';
                draw();
            });
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
