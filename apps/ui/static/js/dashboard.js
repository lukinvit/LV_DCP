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
        tooltip.style.cssText = 'position:absolute;padding:4px 8px;background:#1a1a2e;color:#eee;border-radius:4px;font-size:12px;pointer-events:none;display:none;white-space:nowrap;z-index:10';
        container.style.position = 'relative';
        container.appendChild(tooltip);

        var hoveredNode = null;
        var expandedCluster = null;
        var transform = d3.zoomIdentity;
        var roleColor = { code: '#2a5caa', test: '#2e7d32', config: '#f57c00', docs: '#888888' };

        d3.json('/api/project/' + slug + '/graph.json').then(function (data) {
            if (!data || !data.clusters || data.clusters.length === 0) {
                if (data && data.nodes && data.nodes.length > 0) {
                    info.textContent = data.nodes.length + ' files (no clusters)';
                } else {
                    info.textContent = 'No graph data';
                }
                return;
            }

            var clusters = data.clusters;
            var allEdges = data.edges || [];
            var activeNodes, activeLinks, neighbors, simulation;

            // Map every file to its cluster
            var _clusterMap = {};
            clusters.forEach(function (c) {
                (c.top_files || []).forEach(function (f) { _clusterMap[f.id] = c.id; });
            });
            (data.nodes || []).forEach(function (n) {
                if (!_clusterMap[n.id]) {
                    var parts = n.id.split('/');
                    _clusterMap[n.id] = parts.length > 2 ? parts.slice(0, 2).join('/') :
                        (parts.length === 2 ? parts[0] : '.');
                }
            });

            function buildClusterView() {
                expandedCluster = null;
                var maxDeg = Math.max(1, d3.max(clusters, function (c) { return c.total_degree; }) || 1);
                var cNodes = clusters.map(function (c) {
                    return {
                        id: c.id, label: c.label, role: c.role,
                        childrenCount: c.children_count, totalDegree: c.total_degree,
                        isCluster: true, degree: c.total_degree,
                        radius: 6 + 14 * Math.sqrt(c.total_degree / maxDeg),
                        files: c.top_files || []
                    };
                });
                var edgeSet = {};
                allEdges.forEach(function (e) {
                    var sc = _clusterMap[e.src], dc = _clusterMap[e.dst];
                    if (sc && dc && sc !== dc) {
                        var key = sc < dc ? sc + '|' + dc : dc + '|' + sc;
                        edgeSet[key] = { source: sc, target: dc };
                    }
                });
                setActive(cNodes, Object.values(edgeSet));
                info.textContent = clusters.length + ' modules, ' + allEdges.length + ' file edges (' + data.nodes.length + ' files total)';
            }

            function buildExpandedView(clusterId) {
                expandedCluster = clusterId;
                var cluster = clusters.find(function (c) { return c.id === clusterId; });
                if (!cluster || !cluster.top_files || cluster.top_files.length === 0) { buildClusterView(); return; }
                var maxFileDeg = Math.max(1, cluster.top_files[0].degree || 1);
                var fNodes = cluster.top_files.map(function (f) {
                    return {
                        id: f.id, label: f.label, role: f.role, degree: f.degree,
                        isCluster: false,
                        radius: 3 + 5 * Math.sqrt(f.degree / maxFileDeg)
                    };
                });
                var fIds = new Set(fNodes.map(function (n) { return n.id; }));
                var fLinks = allEdges
                    .filter(function (e) { return fIds.has(e.src) && fIds.has(e.dst); })
                    .map(function (e) { return { source: e.src, target: e.dst }; });
                setActive(fNodes, fLinks);
                info.textContent = cluster.label + ': ' + fNodes.length + ' files, ' + fLinks.length + ' edges (click background to collapse)';
            }

            function setActive(nodes, links) {
                activeNodes = nodes;
                activeLinks = links;
                neighbors = {};
                links.forEach(function (l) {
                    var s = typeof l.source === 'object' ? l.source.id : l.source;
                    var t = typeof l.target === 'object' ? l.target.id : l.target;
                    if (!neighbors[s]) neighbors[s] = new Set();
                    if (!neighbors[t]) neighbors[t] = new Set();
                    neighbors[s].add(t);
                    neighbors[t].add(s);
                });
                if (simulation) simulation.stop();
                simulation = d3.forceSimulation(activeNodes)
                    .force('link', d3.forceLink(activeLinks).id(function (d) { return d.id; }).distance(60))
                    .force('charge', d3.forceManyBody().strength(-40))
                    .force('center', d3.forceCenter(canvas.width / 2, canvas.height / 2))
                    .alphaDecay(0.02)
                    .on('tick', draw);
            }

            function draw() {
                ctx.save();
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.translate(transform.x, transform.y);
                ctx.scale(transform.k, transform.k);
                var hId = hoveredNode ? hoveredNode.id : null;
                var hN = hId && neighbors[hId] ? neighbors[hId] : null;

                activeLinks.forEach(function (l) {
                    var sId = l.source.id || l.source, tId = l.target.id || l.target;
                    var active = hId && (sId === hId || tId === hId);
                    ctx.strokeStyle = active ? '#e74c3c' : (hId ? 'rgba(200,200,200,0.15)' : 'rgba(180,180,180,0.4)');
                    ctx.lineWidth = active ? 2 : 0.5;
                    ctx.beginPath();
                    ctx.moveTo(l.source.x, l.source.y);
                    ctx.lineTo(l.target.x, l.target.y);
                    ctx.stroke();
                });

                activeNodes.forEach(function (n) {
                    var isH = hId === n.id, isN = hN && hN.has(n.id);
                    var dim = hId && !isH && !isN;
                    var r = isH ? n.radius + 3 : n.radius;
                    ctx.beginPath();
                    ctx.arc(n.x, n.y, r, 0, 2 * Math.PI);
                    var base = roleColor[n.role] || '#666666';
                    ctx.fillStyle = dim ? 'rgba(180,180,180,0.3)' : base;
                    ctx.fill();
                    if (n.isCluster) { ctx.strokeStyle = 'rgba(0,0,0,0.3)'; ctx.lineWidth = 1.5; ctx.stroke(); }
                    if (isH) { ctx.strokeStyle = '#e74c3c'; ctx.lineWidth = 2; ctx.stroke(); }
                    if (n.isCluster || isH) {
                        ctx.fillStyle = '#333';
                        ctx.font = (n.isCluster ? '11px' : '10px') + ' system-ui, sans-serif';
                        ctx.textAlign = 'center';
                        ctx.fillText(n.label + (n.isCluster ? ' (' + n.childrenCount + ')' : ''), n.x, n.y + r + 12);
                    }
                });
                ctx.restore();
            }

            d3.select(canvas).call(d3.zoom().scaleExtent([0.3, 5]).on('zoom', function (event) {
                transform = event.transform;
                draw();
            }));

            function hitTest(e) {
                var rect = canvas.getBoundingClientRect();
                var mx = (e.clientX - rect.left - transform.x) / transform.k;
                var my = (e.clientY - rect.top - transform.y) / transform.k;
                for (var i = activeNodes.length - 1; i >= 0; i--) {
                    var n = activeNodes[i], dx = mx - n.x, dy = my - n.y;
                    if (dx * dx + dy * dy < (n.radius + 3) * (n.radius + 3)) return n;
                }
                return null;
            }

            canvas.addEventListener('click', function (e) {
                var found = hitTest(e);
                if (found && found.isCluster) buildExpandedView(found.id);
                else if (!found && expandedCluster) buildClusterView();
            });

            canvas.addEventListener('mousemove', function (e) {
                var found = hitTest(e);
                if (found !== hoveredNode) {
                    hoveredNode = found;
                    if (found) {
                        tooltip.textContent = found.isCluster
                            ? found.label + ' \u2014 ' + found.childrenCount + ' files, ' + found.totalDegree + ' connections'
                            : found.id + ' (' + found.degree + ' connections)';
                        tooltip.style.display = 'block';
                        canvas.style.cursor = 'pointer';
                    } else {
                        tooltip.style.display = 'none';
                        canvas.style.cursor = 'default';
                    }
                    draw();
                }
                if (found) {
                    tooltip.style.left = (e.clientX - container.getBoundingClientRect().left + 12) + 'px';
                    tooltip.style.top = (e.clientY - container.getBoundingClientRect().top - 8) + 'px';
                }
            });

            canvas.addEventListener('mouseleave', function () {
                hoveredNode = null;
                tooltip.style.display = 'none';
                canvas.style.cursor = 'default';
                draw();
            });

            buildClusterView();
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
