// 全局变量
let map;
let predictedMarkers = [];
let actualMarkers = [];
let probeMarkers = [];
let connectionLines = [];
let intersectionCircles = [];
let intersectionAreas = []; // 存储交集区域图层
let performanceData = {}; // 存储性能数据
let cdfChart = null; // CDF图表实例
let data = {
    predicted: [],
    actual: [],
    probes: [],
    circles: {}, // 存储交圆数据，按IP分组
    intersections: {} // 存储交集几何数据，按IP分组
};

// 数据集管理
let currentDatasetId = '1_3'; // 默认数据集
let availableDatasets = []; // 可用数据集列表

// 交圆缩放比例
let circleScaleFactor = 1.0;

// 设置一个标志，表示已经固定了详细信息
let isDetailFixed = false;
// 设置一个变量，跟踪当前被锁定的点
let currentLockedIndex = null;

// 全局圆动画变量
let circleAnimations = {};

// 自定义图标
const icons = {
    predicted: L.icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    }),
    actual: L.icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    }),
    probe: L.icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    }),
    // 添加紫色探针图标，用于高亮形成交圆的探针
    probeHighlight: L.icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-violet.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [25, 41],
        iconAnchor: [12, 41],
        popupAnchor: [1, -34],
        shadowSize: [41, 41]
    }),
    // 添加高亮图标
    predictedHighlight: L.icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [35, 57], // 放大图标
        iconAnchor: [17, 57],
        popupAnchor: [1, -34],
        shadowSize: [41, 41],
        className: 'highlighted-marker' // 添加CSS类
    }),
    actualHighlight: L.icon({
        iconUrl: 'https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png',
        shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/0.7.7/images/marker-shadow.png',
        iconSize: [35, 57], // 放大图标
        iconAnchor: [17, 57],
        popupAnchor: [1, -34],
        shadowSize: [41, 41],
        className: 'highlighted-marker' // 添加CSS类
    })
};

// 默认交圆样式
const defaultIntersectionStyle = {
    color: '#9c27b0',
    fillColor: '#9c27b0',
    fillOpacity: 0.05,
    weight: 1,
    className: 'intersection-circle'
};

// Octant环形区域样式
const octantRingStyle = {
    color: '#ff5722',
    fillColor: '#ff5722',
    fillOpacity: 0.08,
    weight: 2,
    className: 'octant-ring',
    dashArray: '5, 5' // 虚线样式，区分CBG圆形
};

// 初始化地图
function initMap() {
    // 定义美洲的大致边界
    const americasBounds = L.latLngBounds(
        L.latLng(-56, -170), // 西南角 (大致南美洲南端，向西扩展)
        L.latLng(84, -20)    // 东北角 (大致格陵兰北端，向东扩展)
    );

    // 美国本土的地理中心大致在 (39.8283° N, 98.5795° W)
    const usaCenter = [39.8283, -98.5795];

    // 创建地图实例
    map = L.map('map', {
        maxBounds: americasBounds, // 限制地图边界到美洲
        maxBoundsViscosity: 0.9, // 允许稍微拖出边界，但有回弹效果
        zoomControl: false 
    }).setView(usaCenter, 4); // 初始视图设置为美国中心，缩放级别4适合显示美国本土

    // 设置地图的最小和最大缩放级别
    map.setMinZoom(2); // 仍然允许缩放到能看清整个美洲的级别
    map.setMaxZoom(16); // 限制最大放大级别

    // 添加OpenStreetMap底图层
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        minZoom: 2, // 配合地图的minZoom
        maxZoom: 16 // 配合地图的maxZoom
    }).addTo(map);
    
    // 点击地图空白处时，重置锁定状态
    map.on('click', function() {
        if (isDetailFixed) {
            isDetailFixed = false;
        }
        
        // 重置锁定点
        if (currentLockedIndex !== null) {
            currentLockedIndex = null;
            resetHighlightedConnections();
            resetHighlightedMarkers();
            clearIntersectionCircles();
            
            // 如果启用了"只展示被选中的IP"功能，需要重新渲染地图
            if (document.getElementById('show-selected-only').checked) {
                renderMapElements();
            }
        }
        
        resetHoverInfo();
    });

    // 创建图例控件
    const legend = L.control({position: 'bottomright'});
    
    legend.onAdd = function(map) {
        const div = L.DomUtil.create('div', 'info legend');
        div.style.backgroundColor = 'white';
        div.style.padding = '10px';
        div.style.borderRadius = '5px';
        div.style.boxShadow = '0 0 15px rgba(0,0,0,0.2)';
        
        div.innerHTML = `
            <div style="margin-bottom: 5px;"><strong>图例</strong></div>
            <div style="display: flex; align-items: center; margin-bottom: 5px;">
                <img src="https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-blue.png" height="20" style="margin-right: 5px;" />
                <span>预测位置</span>
            </div>
            <div style="display: flex; align-items: center; margin-bottom: 5px;">
                <img src="https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-red.png" height="20" style="margin-right: 5px;" />
                <span>实际位置</span>
            </div>
            <div style="display: flex; align-items: center; margin-bottom: 5px;">
                <img src="https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-green.png" height="20" style="margin-right: 5px;" />
                <span>探针</span>
            </div>
            <div style="display: flex; align-items: center; margin-bottom: 5px;">
                <img src="https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-violet.png" height="20" style="margin-right: 5px;" />
                <span>形成交圆的探针</span>
            </div>
            <div style="margin-top: 5px; border-top: 1px solid #ccc; padding-top: 5px;">
                <div style="height: 4px; width: 30px; background-color: gray; margin-right: 5px; display: inline-block;"></div>
                <span>连接线</span>
            </div>
            <div style="margin-top: 5px;">
                <div style="height: 10px; width: 10px; border-radius: 50%; background-color: rgba(156, 39, 176, 0.3); border: 1px solid #9c27b0; margin-right: 5px; display: inline-block;"></div>
                <span>CBG交圆</span>
            </div>
            <div style="margin-top: 5px;">
                <div style="display: flex; align-items: center;">
                    <div style="position: relative; margin-right: 5px;">
                        <div style="height: 14px; width: 14px; border-radius: 50%; background-color: rgba(255, 87, 34, 0.02); border: 2px solid #ff5722; display: inline-block;"></div>
                        <div style="position: absolute; top: 2px; left: 2px; height: 10px; width: 10px; border-radius: 50%; background-color: rgba(255, 87, 34, 0.02); border: 2px dashed #ff5722; display: inline-block;"></div>
                    </div>
                    <span>Octant环形 (外实内虚)</span>
                </div>
            </div>
            <div style="margin-top: 5px;">
                <div style="height: 10px; width: 20px; background-color: rgba(255, 235, 59, 0.6); border: 1px solid #f57f17; margin-right: 5px; display: inline-block;"></div>
                <span>交集区域</span>
            </div>
        `;
        
        return div;
    };
    
    // 添加图例到地图
    legend.addTo(map);

    // 初始化性能分析功能
    initializePerformanceAnalysis();
    
    // 初始加载数据
    loadData();
    
    // 设置控件事件
    setupControls();
    
    // 设置搜索功能
    setupSearch();
    
    // 设置数据集管理功能
    setupDatasetManager();

    setupCustomZoomControls();
}

// 数据集管理相关函数
async function setupDatasetManager() {
    // 加载方法列表
    await loadDatasets();
    
    // 设置方法选择器事件
    const datasetSelect = document.getElementById('dataset-select');
    
    datasetSelect.addEventListener('change', function() {
        const selectedDatasetId = this.value;
        if (selectedDatasetId && selectedDatasetId !== currentDatasetId) {
            switchDataset(selectedDatasetId);
        }
    });
}

// 加载可用数据集列表
async function loadDatasets() {
    try {
        // 添加时间戳参数避免浏览器缓存
        const timestamp = new Date().getTime();
        const response = await fetch(`/api/datasets?t=${timestamp}`);
        if (!response.ok) {
            throw new Error(`获取方法列表失败: ${response.status}`);
        }
        
        availableDatasets = await response.json();
        updateDatasetSelector();
        
    } catch (error) {
        console.error('加载方法列表失败:', error);
        const datasetSelect = document.getElementById('dataset-select');
        datasetSelect.innerHTML = '<option value="">加载失败</option>';
    }
}

// 更新数据集选择器
function updateDatasetSelector() {
    const datasetSelect = document.getElementById('dataset-select');
    datasetSelect.innerHTML = '';
    
    if (availableDatasets.length === 0) {
        datasetSelect.innerHTML = '<option value="">无可用方法</option>';
        return;
    }
    
    availableDatasets.forEach(dataset => {
        const option = document.createElement('option');
        option.value = dataset.id;
        option.textContent = dataset.name;
        
        // 如果是当前数据集，设置为选中状态
        if (dataset.id === currentDatasetId) {
            option.selected = true;
        }
        
        datasetSelect.appendChild(option);
    });
}

// 切换数据集
async function switchDataset(datasetId) {
    try {
        // 显示加载状态
        document.getElementById('stats').innerHTML = '正在切换方法...';
        
        // 加载新数据集
        await loadData(datasetId);
        
        // 更新选择器状态
        updateDatasetSelector();
        
    } catch (error) {
        console.error('切换方法失败:', error);
        document.getElementById('stats').innerHTML = `切换方法失败: ${error.message}`;
    }
}

// 设置搜索功能
function setupSearch() {
    const searchButton = document.getElementById('search-button');
    const searchInput = document.getElementById('ip-search');
    
    // 点击搜索按钮时触发搜索
    searchButton.addEventListener('click', function() {
        searchIP(searchInput.value.trim());
    });
    
    // 按回车键也触发搜索
    searchInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') {
            searchIP(searchInput.value.trim());
        }
    });
}

// 搜索IP并模拟点击
function searchIP(ip) {
    if (!ip) {
        alert('请输入要搜索的IP地址');
        return;
    }
    
    // 查找对应的预测位置标记
    let found = false;
    
    for (let i = 0; i < data.predicted.length; i++) {
        if (data.predicted[i].ip === ip) {
            // 找到匹配的IP
            found = true;
            
            // 缩放到该点
            const point = data.predicted[i];
            map.setView([point.lat, point.lng], 8);
            
            // 模拟点击该点
            simulateMarkerClick(i);
            
            break;
        }
    }
    
    if (!found) {
        alert('未找到IP为 ' + ip + ' 的点');
    }
}

// 模拟点击标记点
function simulateMarkerClick(index) {
    if (index >= 0 && index < predictedMarkers.length) {
        // 如果点击的是当前已锁定的点，不做任何操作（保持选中状态）
        if (currentLockedIndex === index) {
            return;
        }
        
        // 如果之前有锁定点，先重置
        if (currentLockedIndex !== null) {
            resetHighlightedConnections();
            resetHighlightedIntersectionCircles();
            resetHighlightedMarkers();
            clearIntersectionCircles();
        }
        
        // 更新锁定点
        currentLockedIndex = index;
        
        // 获取点数据
        const point = data.predicted[index];
        const actualPoint = data.actual[index];
        
        // 如果启用了"只展示被选中的IP"功能，重新渲染地图
        if (document.getElementById('show-selected-only').checked) {
            renderMapElements();
        } else {
            // 否则只高亮标记
            highlightMarkers(index);
            
            // 显示该IP的交圆
            if (document.getElementById('show-circles').checked) {
                showIntersectionCirclesForIP(point.ip);
            }
            
            // 如果交集区域选项被勾选，显示该IP的交集区域
            if (document.getElementById('show-intersection').checked) {
                showIntersectionAreaForIP(point.ip);
            }
        }
        
        // 显示详细信息
        const detailInfo = `
            <h4>IP: ${point.ip}</h4>
            <div class="detail-section">
                <strong>预测位置:</strong>
                <div>经纬度: ${point.lng.toFixed(6)}, ${point.lat.toFixed(6)}</div>
                <div>州: ${point.state}</div>
            </div>
            <div class="detail-section">
                <strong>实际位置:</strong>
                <div>经纬度: ${actualPoint.lng.toFixed(6)}, ${actualPoint.lat.toFixed(6)}</div>
                <div>州: ${actualPoint.state}</div>
            </div>
            <div class="detail-section">
                <strong>距离误差:</strong> 
                ${getDistanceFromLatLonInKm(point.lat, point.lng, actualPoint.lat, actualPoint.lng).toFixed(2)} 公里
            </div>
        `;
        
        document.getElementById('hover-info').innerHTML = detailInfo;
        isDetailFixed = true;
    }
}

// 加载数据文件
async function loadData(datasetId = null) {
    try {
        // 如果指定了数据集ID，则使用指定的；否则使用当前的
        const targetDatasetId = datasetId || currentDatasetId;
        
        // 清空之前的数据
        data.predicted = [];
        data.actual = [];
        data.probes = [];
        data.circles = {};
        data.intersections = {};
        
        // 添加时间戳参数避免浏览器缓存
        const timestamp = new Date().getTime();
        
        // 加载预测与实际位置数据
        const resultsResponse = await fetch(`/api/data/user_result_loc/${targetDatasetId}?t=${timestamp}`);
        if (!resultsResponse.ok) {
            throw new Error(`加载result_loc数据失败: ${resultsResponse.status}`);
        }
        const results = await resultsResponse.json();
        
        // 加载探针数据（探针数据通常不变）
        const probesResponse = await fetch(`/api/data/user_probes?t=${timestamp}`);
        if (!probesResponse.ok) {
            throw new Error(`加载probes数据失败: ${probesResponse.status}`);
        }
        const probes = await probesResponse.json();
        
        // 加载交圆数据
        const circlesResponse = await fetch(`/api/data/user_circle_map/${targetDatasetId}?t=${timestamp}`);
        if (!circlesResponse.ok) {
            throw new Error(`加载circle_map数据失败: ${circlesResponse.status}`);
        }
        const circlesData = await circlesResponse.json();
        
        // 更新当前数据集ID
        currentDatasetId = targetDatasetId;
        
        // 处理数据
        processData(results, probes, circlesData);
        
        // 重置锁定状态
        currentLockedIndex = null;
        isDetailFixed = false;
        
        // 更新统计信息
        updateStats();
        
        // 绘制地图元素
        renderMapElements();
        
        // 重置信息面板
        resetHoverInfo();
        
        console.log(`成功加载数据集: ${targetDatasetId}`);
        
    } catch (error) {
        console.error('加载数据失败:', error);
        document.getElementById('stats').innerHTML = `加载数据失败: ${error.message}`;
    }
}

// 处理数据
function processData(results, probes, circlesData) {
    // 处理结果数据
    results.forEach(item => {
        if (item[2] && item[2].length === 2 && item[3] && item[3].length === 2) {
            // 修正：JSON中是[经度, 纬度]顺序
            const predictedLon = item[2][0];
            const predictedLat = item[2][1];
            const actualLon = item[3][0];
            const actualLat = item[3][1];
            
            // 过滤无效坐标 (美国范围内)
            if (isInUSA(predictedLon, predictedLat) && isInUSA(actualLon, actualLat)) {
                // 扩展存储的数据，包括IP和州信息
                const predictedInfo = {
                    lat: predictedLat,
                    lng: predictedLon,
                    id: item[0],
                    ip: item[0], // 假设ID是IP
                    state: item[5] || '未知', // 预测位置州信息在数组的第5个元素
                    fullInfo: item
                };
                
                const actualInfo = {
                    lat: actualLat,
                    lng: actualLon,
                    id: item[0],
                    ip: item[0], // 假设ID是IP
                    state: item[6] || '未知', // 实际位置州信息在数组的第6个元素
                    fullInfo: item
                };
                
                data.predicted.push(predictedInfo);
                data.actual.push(actualInfo);
            }
        }
    });
    
    // 处理探针数据 - 探针数据特殊处理：先纬度后经度
    probes.forEach(probe => {
        if (probe.geometry && probe.geometry.coordinates) {
            // 探针数据特殊处理：先纬度后经度
            const lat = probe.geometry.coordinates[0]; // 纬度是第一个元素
            const lng = probe.geometry.coordinates[1]; // 经度是第二个元素
            
            if (isInUSA(lng, lat)) {
                data.probes.push({
                    lat: lat,
                    lng: lng,
                    id: probe.id || probe.properties?.id || '未知ID',
                    state: probe.properties?.state || '未知',
                    fullInfo: probe
                });
            }
        }
    });
    
    // 处理交圆数据 - 按IP分组存储，不立即添加到地图
    for (const ip in circlesData) {
        if (circlesData.hasOwnProperty(ip)) {
            let circles = [];
            let intersectionGeometry = null;
            
            // 检查是否为新的Octant数据结构
            if (circlesData[ip] && typeof circlesData[ip] === 'object' && circlesData[ip].rings) {
                // 新的Octant数据结构：{rings: [...], intersection_geometry: {...}}
                const octantData = circlesData[ip];
                
                // 处理环形数据
                if (octantData.rings && Array.isArray(octantData.rings)) {
                    octantData.rings.forEach(circle => {
                        if (Array.isArray(circle) && circle.length === 7) {
                            // Octant格式：[lon, lat, rtt, d_km, r, inner_radius_km, outer_radius_km]
                            const [circleLon, circleLat, rtt, originalRadius, , innerRadius, outerRadius] = circle;
                            
                            const circleObj = {
                                center: [circleLat, circleLon],
                                radius: originalRadius * 1000, // 公里转换为米
                                originalRadius: originalRadius, // 保存原始半径（公里）
                                rtt: rtt,
                                ip: ip,
                                innerRadius: innerRadius,
                                outerRadius: outerRadius
                            };
                            
                            circles.push(circleObj);
                        }
                    });
                }
                
                // 提取交集几何数据
                if (octantData.intersection_geometry) {
                    intersectionGeometry = octantData.intersection_geometry;
                }
                
            } else if (Array.isArray(circlesData[ip])) {
                // 原有的数组格式（CBG或旧Octant格式）
                circlesData[ip].forEach(circle => {
                    let circleLon, circleLat, rtt, radius, originalRadius, innerRadius, outerRadius;
                    
                    // 检查数据格式
                    if (Array.isArray(circle)) {
                        if (circle.length === 7) {
                            // 新的Octant格式：[lon, lat, rtt, d_km, r, inner_radius_km, outer_radius_km]
                            circleLon = circle[0];
                            circleLat = circle[1];
                            rtt = circle[2];
                            originalRadius = circle[3]; // 基础半径（公里）
                            radius = circle[3] * 1000; // 公里转换为米
                            innerRadius = circle[5]; // 内半径（公里）
                            outerRadius = circle[6]; // 外半径（公里）
                        } else if (circle.length === 5) {
                            // CBG格式：[经度, 纬度, rtt, 半径d, 归一化半径r]
                            circleLon = circle[0];
                            circleLat = circle[1];
                            rtt = circle[2];
                            originalRadius = circle[3]; // 公里
                            radius = circle[3] * 1000; // 公里转换为米
                            innerRadius = null;
                            outerRadius = null;
                        } else {
                            console.warn('未知的数组格式圆形数据长度:', circle.length, circle);
                            return;
                        }
                    } else if (typeof circle === 'object' && circle.hasOwnProperty('lon')) {
                        // 旧的字典格式（向后兼容）
                        circleLon = circle.lon;
                        circleLat = circle.lat;
                        rtt = circle.rtt;
                        originalRadius = circle.base_radius_km || circle[3];
                        radius = originalRadius * 1000;
                        innerRadius = circle.inner_radius_km;
                        outerRadius = circle.outer_radius_km;
                    } else {
                        console.warn('未知的圆形数据格式:', circle);
                        return;
                    }
                    
                    // 创建圆对象，但不添加到地图
                    const circleObj = {
                        center: [circleLat, circleLon],
                        radius: radius,
                        originalRadius: originalRadius, // 保存原始半径（公里）
                        rtt: rtt,
                        ip: ip
                    };
                    
                    // 如果有内外半径数据，也保存
                    if (innerRadius !== null && outerRadius !== null) {
                        circleObj.innerRadius = innerRadius;
                        circleObj.outerRadius = outerRadius;
                    }
                    
                    circles.push(circleObj);
                });
            }
            
            // 存储到全局数据中
            data.circles[ip] = circles;
            
            // 存储交集几何数据
            if (intersectionGeometry) {
                data.intersections[ip] = intersectionGeometry;
            }
        }
    }
}

// 检查坐标是否在美国范围内
function isInUSA(lon, lat) {
    return lon > -130 && lon < -60 && lat > 20 && lat < 50;
}

// 更新统计信息
function updateStats() {
    const statsElem = document.getElementById('stats');
    const currentDatasetName = availableDatasets.find(ds => ds.id === currentDatasetId)?.name || `方法 ${currentDatasetId}`;
    
    statsElem.innerHTML = `
        <strong>${currentDatasetName}</strong> | 
        预测位置: ${data.predicted.length} | 
        实际位置: ${data.actual.length} | 
        探针: ${data.probes.length}
    `;
}

// 渲染地图元素
function renderMapElements() {
    // 清除之前的标记
    clearMapElements();
    
    // 检查是否启用了"只展示被选中的IP"功能
    const showSelectedOnly = document.getElementById('show-selected-only').checked;
    
    // 如果启用了"只展示被选中的IP"但没有选中任何IP，显示提示
    if (showSelectedOnly && currentLockedIndex === null) {
        updateHoverInfo('请先点击一个预测位置或实际位置，然后勾选"只展示被选中的IP"');
        return;
    }
    
    // 添加探针标记
    if (document.getElementById('show-probes').checked) {
        addProbeMarkers(showSelectedOnly);
    }
    
    // 添加预测位置标记
    if (document.getElementById('show-predictions').checked) {
        addPredictedMarkers(showSelectedOnly);
    }
    
    // 添加实际位置标记
    if (document.getElementById('show-actuals').checked) {
        addActualMarkers(showSelectedOnly);
    }
    
    // 添加连接线
    if (document.getElementById('show-lines').checked) {
        addConnectionLines(showSelectedOnly);
    }
    
    // 如果有选中的IP且显示交圆选项被勾选，显示交圆
    if (currentLockedIndex !== null && document.getElementById('show-circles').checked) {
        const point = data.predicted[currentLockedIndex];
        showIntersectionCirclesForIP(point.ip);
    }
    
    // 如果有选中的IP且显示交集区域选项被勾选，显示交集区域
    if (currentLockedIndex !== null && document.getElementById('show-intersection').checked) {
        const point = data.predicted[currentLockedIndex];
        showIntersectionAreaForIP(point.ip);
    }
}

// 清除地图元素
function clearMapElements() {
    // 清除预测位置标记
    predictedMarkers.forEach(marker => marker.remove());
    predictedMarkers = [];
    
    // 清除实际位置标记
    actualMarkers.forEach(marker => marker.remove());
    actualMarkers = [];
    
    // 清除探针标记
    probeMarkers.forEach(marker => marker.remove());
    probeMarkers = [];
    
    // 清除连接线
    connectionLines.forEach(line => line.remove());
    connectionLines = [];
    
    // 清除交圆
    clearIntersectionCircles();
    
    // 清除交集区域
    clearIntersectionAreas();
}

// 清除交圆
function clearIntersectionCircles() {
    intersectionCircles.forEach(circle => circle.remove());
    intersectionCircles = [];
    
    // 同时重置探针高亮状态
    resetProbeHighlights();
}

// 清除交集区域
function clearIntersectionAreas() {
    intersectionAreas.forEach(area => area.remove());
    intersectionAreas = [];
}

// 显示特定IP的交圆
function showIntersectionCirclesForIP(ip) {
    console.log("Showing circles for IP:", ip, "Data:", data.circles[ip]); // 添加日志
    // 先清除现有的交圆
    clearIntersectionCircles();
    
    // 重置探针高亮状态
    resetProbeHighlights();
    
    // 检查是否有该IP的交圆数据
    if (data.circles[ip]) {
        const circles = data.circles[ip];
        
        // 判断是否为Octant方法
        const isOctantMethod = currentDatasetId === 'octant' || currentDatasetId.startsWith('octant_');
        
        // 遍历该IP的所有交圆
        circles.forEach(circleData => {
            if (isOctantMethod) {
                // Octant方法：绘制环形区域（内环 + 外环）
                let innerRadius, outerRadius;
                
                // 检查是否有预计算的内外半径
                if (circleData.innerRadius !== undefined && circleData.outerRadius !== undefined) {
                    // 使用预计算的内外半径（公里转米）
                    innerRadius = circleData.innerRadius * 1000 * circleScaleFactor;
                    outerRadius = circleData.outerRadius * 1000 * circleScaleFactor;
                } else {
                    // 回退到旧的比例计算
                    const innerRatio = 2/3; // 内半径比例
                    const outerRatio = 4/3; // 外半径比例
                    
                    const baseRadius = circleData.radius * circleScaleFactor;
                    innerRadius = baseRadius * innerRatio;
                    outerRadius = baseRadius * outerRatio;
                }
                
                // 绘制外圆（橙色实线）
                const outerCircle = L.circle(circleData.center, {
                    radius: outerRadius,
                    color: '#ff5722',
                    fillColor: '#ff5722',
                    fillOpacity: 0.02,
                    weight: 2,
                    // dashArray: '5, 5', // 移除虚线样式，改为实线
                    className: 'octant-outer-ring',
                    ip: ip,
                    rtt: circleData.rtt,
                    type: 'outer'
                }).addTo(map);
                
                // 绘制内圆（橙色虚线）
                const innerCircle = L.circle(circleData.center, {
                    radius: innerRadius,
                    color: '#ff5722',
                    fillColor: '#ff5722',
                    fillOpacity: 0.02,
                    weight: 2,
                    dashArray: '5, 5',
                    className: 'octant-inner-ring',
                    ip: ip,
                    rtt: circleData.rtt,
                    type: 'inner'
                }).addTo(map);
                
                // 添加点击事件
                [outerCircle, innerCircle].forEach(circle => {
                    circle.on('click', function(e) {
                        L.DomEvent.stopPropagation(e);
                        
                        // 计算显示用的半径数据
                        const displayInnerRadius = circleData.innerRadius !== undefined ? 
                            circleData.innerRadius : (circleData.originalRadius * 2/3);
                        const displayOuterRadius = circleData.outerRadius !== undefined ? 
                            circleData.outerRadius : (circleData.originalRadius * 4/3);
                        
                        // 显示详细信息
                        const detailInfo = `
                            <h4>Octant环形区域</h4>
                            <div class="detail-section">
                                <strong>IP:</strong> ${ip}
                            </div>
                            <div class="detail-section">
                                <strong>RTT:</strong> ${circleData.rtt}ms
                            </div>
                            <div class="detail-section">
                                <strong>基础半径:</strong> ${circleData.originalRadius.toFixed(2)} 公里
                            </div>
                            <div class="detail-section">
                                <strong>内半径:</strong> ${displayInnerRadius.toFixed(2)} 公里
                            </div>
                            <div class="detail-section">
                                <strong>外半径:</strong> ${displayOuterRadius.toFixed(2)} 公里
                            </div>
                            <div class="detail-section">
                                <strong>中心坐标:</strong> [${circleData.center[0].toFixed(4)}, ${circleData.center[1].toFixed(4)}]
                            </div>
                        `;
                        
                        document.getElementById('hover-info').innerHTML = detailInfo;
                        isDetailFixed = true;
                    });
                });
                
                // 保存到交圆数组
                intersectionCircles.push(outerCircle, innerCircle);
                
            } else {
                // CBG方法：绘制普通圆形
            const circle = L.circle(circleData.center, {
                radius: circleData.radius * circleScaleFactor, // 应用缩放比例因子
                ...defaultIntersectionStyle,
                ip: ip,
                rtt: circleData.rtt
            }).addTo(map);
            
                // 添加点击事件
            circle.on('click', function(e) {
                L.DomEvent.stopPropagation(e);
                
                // 显示详细信息
                const detailInfo = `
                        <h4>CBG交圆信息</h4>
                    <div class="detail-section">
                        <strong>IP:</strong> ${ip}
                    </div>
                    <div class="detail-section">
                        <strong>RTT:</strong> ${circleData.rtt}ms
                    </div>
                    <div class="detail-section">
                        <strong>半径:</strong> ${circleData.originalRadius.toFixed(2)} 公里
                    </div>
                    <div class="detail-section">
                        <strong>中心坐标:</strong> [${circleData.center[0].toFixed(4)}, ${circleData.center[1].toFixed(4)}]
                    </div>
                `;
                
                document.getElementById('hover-info').innerHTML = detailInfo;
                isDetailFixed = true;
            });
            
            // 保存到交圆数组
            intersectionCircles.push(circle);
            }
        });
        
        // 高亮形成交圆的探针
        highlightCircleProbes(ip);
    }
}

// 显示特定IP的交集区域
function showIntersectionAreaForIP(ip) {
    console.log("Showing intersection area for IP:", ip, "Data:", data.intersections[ip]);
    
    // 先清除现有的交集区域
    clearIntersectionAreas();
    
    // 检查是否有该IP的交集几何数据
    if (data.intersections[ip]) {
        const intersectionGeometry = data.intersections[ip];
        
        try {
            // 使用Leaflet的geoJSON方法绘制交集区域
            const intersectionLayer = L.geoJSON(intersectionGeometry, {
                style: {
                    fillColor: '#ffeb3b',    // 黄色填充
                    fillOpacity: 0.6,        // 适中透明度
                    color: '#f57f17',        // 深黄色边框
                    weight: 2,
                    className: 'intersection-area'
                }
            }).addTo(map);
            
            // 添加点击事件显示详细信息
            intersectionLayer.on('click', function(e) {
                L.DomEvent.stopPropagation(e);
                
                // 显示交集区域信息
                const detailInfo = `
                    <h4>环形区域交集</h4>
                    <div class="detail-section">
                        <strong>IP:</strong> ${ip}
                    </div>
                    <div class="detail-section">
                        <strong>几何类型:</strong> ${intersectionGeometry.type}
                    </div>
                    <div class="detail-section">
                        <strong>描述:</strong> 所有环形区域的公共交集区域
                    </div>
                `;
                
                document.getElementById('hover-info').innerHTML = detailInfo;
                isDetailFixed = true;
            });
            
            // 保存到交集区域数组
            intersectionAreas.push(intersectionLayer);
            
            console.log(`成功显示IP ${ip} 的交集区域`);
            
        } catch (error) {
            console.error(`绘制交集区域时出错: ${error}`);
        }
    } else {
        console.log(`IP ${ip} 没有交集几何数据`);
    }
}

// 添加探针标记
function addProbeMarkers(showSelectedOnly = false) {
    data.probes.forEach(probe => {
        // 探针始终显示，不受"只展示被选中的IP"功能影响
        // 因为探针是重要的参考点
        
        const marker = L.marker([probe.lat, probe.lng], {
            icon: icons.probe,
            zIndexOffset: 1000 // 确保探针在最前面
        }).addTo(map);
        
        // 为探针标记添加探针数据引用，方便后续匹配
        marker._probe = probe;
        
        marker.bindPopup(`<strong>探针ID:</strong> ${probe.id}<br><strong>位置:</strong> ${probe.lat.toFixed(4)}, ${probe.lng.toFixed(4)}`);
        
        // 添加鼠标悬停事件
        marker.on('mouseover', function() {
            this.openPopup();
            updateHoverInfo(`探针 ID: ${probe.id}, 位置: [${probe.lat.toFixed(4)}, ${probe.lng.toFixed(4)}]`);
        });
        
        marker.on('mouseout', function() {
            this.closePopup();
            resetHoverInfo();
        });
        
        probeMarkers.push(marker);
    });
}

// 添加预测位置标记
function addPredictedMarkers(showSelectedOnly = false) {
    data.predicted.forEach((point, index) => {
        // 如果启用了只显示选中IP功能，且当前有选中的IP，只显示选中的IP
        if (showSelectedOnly && currentLockedIndex !== null && index !== currentLockedIndex) {
            return;
        }
        
        const marker = L.marker([point.lat, point.lng], {
            icon: icons.predicted,
            id: point.id,
            dataIndex: index
        }).addTo(map);
        
        // 获取对应的实际位置
        const actualPoint = data.actual[index];
        
        // 创建更详细的弹出窗口内容
        const popupContent = `
            <div class="popup-content">
                <h4>ID: ${point.id}</h4>
                <div class="popup-section">
                    <strong>预测位置:</strong> 
                    <div>${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}</div>
                    <div>州: ${point.state}</div>
                </div>
                <div class="popup-section">
                    <strong>实际位置:</strong> 
                    <div>${actualPoint.lat.toFixed(4)}, ${actualPoint.lng.toFixed(4)}</div>
                    <div>州: ${actualPoint.state}</div>
                </div>
            </div>
        `;
        
        marker.bindPopup(popupContent);
        
        // 生成悬停显示的信息
        const hoverInfo = `
            IP: ${point.ip} | 
            预测: [${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}] ${point.state} | 
            实际: [${actualPoint.lat.toFixed(4)}, ${actualPoint.lng.toFixed(4)}] ${actualPoint.state}
        `;
        
        // 添加鼠标悬停事件
        marker.on('mouseover', function() {
            this.openPopup();
            if (!isDetailFixed) {
                updateHoverInfo(hoverInfo);
            }
            
            // 如果没有锁定点，才进行高亮显示
            if (currentLockedIndex === null) {
                // 高亮连接线
                highlightConnection(index);
            }
        });
        
        marker.on('mouseout', function() {
            this.closePopup();
            if (!isDetailFixed) {
                resetHoverInfo();
            }
            
            // 如果没有锁定点，才重置高亮
            if (currentLockedIndex === null) {
                // 重置连接线高亮
                resetHighlightedConnections();
            }
        });
        
        // 添加点击事件，固定显示详细信息
        marker.on('click', function(e) {
            // 阻止事件传播
            L.DomEvent.stopPropagation(e);
            
            // 如果点击的是当前已锁定的点，不做任何操作（保持选中状态）
            if (currentLockedIndex === index) {
                return;
            }
            
            // 否则，锁定新的点
            // 先重置之前的设置
            if (currentLockedIndex !== null) {
                resetHighlightedConnections();
                resetHighlightedMarkers();
                clearIntersectionCircles();
            }
            
            // 更新锁定点
            currentLockedIndex = index;
            
            // 如果启用了"只展示被选中的IP"功能，重新渲染地图
            if (document.getElementById('show-selected-only').checked) {
                renderMapElements();
            } else {
                // 否则只高亮标记
                highlightMarkers(index);
                
                // 如果交圆选项被勾选，显示该IP的交圆
                if (document.getElementById('show-circles').checked) {
                    showIntersectionCirclesForIP(point.ip);
                }
                
                // 如果交集区域选项被勾选，显示该IP的交集区域
                if (document.getElementById('show-intersection').checked) {
                    showIntersectionAreaForIP(point.ip);
                }
            }
            
            // 显示详细信息
            const detailInfo = `
                <h4>IP: ${point.ip}</h4>
                <div class="detail-section">
                    <strong>预测位置:</strong>
                    <div>经纬度: ${point.lng.toFixed(6)}, ${point.lat.toFixed(6)}</div>
                    <div>州: ${point.state}</div>
                </div>
                <div class="detail-section">
                    <strong>实际位置:</strong>
                    <div>经纬度: ${actualPoint.lng.toFixed(6)}, ${actualPoint.lat.toFixed(6)}</div>
                    <div>州: ${actualPoint.state}</div>
                </div>
                <div class="detail-section">
                    <strong>距离误差:</strong> 
                    ${getDistanceFromLatLonInKm(point.lat, point.lng, actualPoint.lat, actualPoint.lng).toFixed(2)} 公里
                </div>
            `;
            
            document.getElementById('hover-info').innerHTML = detailInfo;
            isDetailFixed = true;
        });
        
        predictedMarkers.push(marker);
    });
}

// 添加实际位置标记
function addActualMarkers(showSelectedOnly = false) {
    data.actual.forEach((point, index) => {
        // 如果启用了只显示选中IP功能，且当前有选中的IP，只显示选中的IP
        if (showSelectedOnly && currentLockedIndex !== null && index !== currentLockedIndex) {
            return;
        }
        
        const marker = L.marker([point.lat, point.lng], {
            icon: icons.actual,
            id: point.id
        }).addTo(map);
        
        // 获取对应的预测位置
        const predictedPoint = data.predicted[index];
        
        // 创建更详细的弹出窗口内容
        const popupContent = `
            <div class="popup-content">
                <h4>ID: ${point.id}</h4>
                <div class="popup-section">
                    <strong>实际位置:</strong> 
                    <div>${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}</div>
                    <div>州: ${point.state}</div>
                </div>
                <div class="popup-section">
                    <strong>预测位置:</strong> 
                    <div>${predictedPoint.lat.toFixed(4)}, ${predictedPoint.lng.toFixed(4)}</div>
                    <div>州: ${predictedPoint.state}</div>
                </div>
            </div>
        `;
        
        marker.bindPopup(popupContent);
        
        // 生成悬停显示的信息
        const hoverInfo = `
            IP: ${point.ip} | 
            实际: [${point.lat.toFixed(4)}, ${point.lng.toFixed(4)}] ${point.state} | 
            预测: [${predictedPoint.lat.toFixed(4)}, ${predictedPoint.lng.toFixed(4)}] ${predictedPoint.state}
        `;
        
        // 添加鼠标悬停事件
        marker.on('mouseover', function() {
            this.openPopup();
            if (!isDetailFixed) {
                updateHoverInfo(hoverInfo);
            }
            
            // 如果没有锁定点，才进行高亮显示
            if (currentLockedIndex === null) {
                // 高亮连接线
                highlightConnection(index);
            }
        });
        
        marker.on('mouseout', function() {
            this.closePopup();
            if (!isDetailFixed) {
                resetHoverInfo();
            }
            
            // 如果没有锁定点，才重置高亮
            if (currentLockedIndex === null) {
                // 重置连接线高亮
                resetHighlightedConnections();
            }
        });
        
        // 添加点击事件，固定显示详细信息
        marker.on('click', function(e) {
            // 阻止事件传播
            L.DomEvent.stopPropagation(e);
            
            // 如果点击的是当前已锁定点对应的实际位置，不做任何操作（保持选中状态）
            if (currentLockedIndex === index) {
                return;
            }
            
            // 否则，锁定新的点
            // 先重置之前的设置
            if (currentLockedIndex !== null) {
                resetHighlightedConnections();
                resetHighlightedMarkers();
                clearIntersectionCircles();
            }
            
            // 更新锁定点
            currentLockedIndex = index;
            
            // 高亮标记
            highlightMarkers(index);
            
            // 如果交圆选项被勾选，显示该IP的交圆
            if (document.getElementById('show-circles').checked) {
                showIntersectionCirclesForIP(point.ip);
            }
            
            // 如果交集区域选项被勾选，显示该IP的交集区域
            if (document.getElementById('show-intersection').checked) {
                showIntersectionAreaForIP(point.ip);
            }
            
            // 显示详细信息
            const detailInfo = `
                <h4>IP: ${point.ip}</h4>
                <div class="detail-section">
                    <strong>实际位置:</strong>
                    <div>经纬度: ${point.lng.toFixed(6)}, ${point.lat.toFixed(6)}</div>
                    <div>州: ${point.state}</div>
                </div>
                <div class="detail-section">
                    <strong>预测位置:</strong>
                    <div>经纬度: ${predictedPoint.lng.toFixed(6)}, ${predictedPoint.lat.toFixed(6)}</div>
                    <div>州: ${predictedPoint.state}</div>
                </div>
                <div class="detail-section">
                    <strong>距离误差:</strong> 
                    ${getDistanceFromLatLonInKm(point.lat, point.lng, predictedPoint.lat, predictedPoint.lng).toFixed(2)} 公里
                </div>
            `;
            
            document.getElementById('hover-info').innerHTML = detailInfo;
            isDetailFixed = true;
        });
        
        actualMarkers.push(marker);
    });
}

// 添加连接线
function addConnectionLines(showSelectedOnly = false) {
    for (let i = 0; i < Math.min(data.predicted.length, data.actual.length); i++) {
        // 如果启用了只显示选中IP功能，且当前有选中的IP，只显示选中IP的连接线
        if (showSelectedOnly && currentLockedIndex !== null && i !== currentLockedIndex) {
            continue;
        }
        
        const predicted = data.predicted[i];
        const actual = data.actual[i];
        
        // 创建连线
        const line = L.polyline(
            [[predicted.lat, predicted.lng], [actual.lat, actual.lng]], 
            {
                color: 'gray',
                weight: 1,
                opacity: 0.3,
                id: predicted.id,
                index: i
            }
        ).addTo(map);
        
        connectionLines.push(line);
    }
}

// 高亮特定连接线
function highlightConnection(index) {
    connectionLines.forEach(line => {
        if (line.options.index === index) {
            line.setStyle({
                weight: 3,
                opacity: 1,
                color: '#ff4081'
            });
            line.bringToFront();
        }
    });
}

// 重置高亮连接线
function resetHighlightedConnections() {
    connectionLines.forEach(line => {
        line.setStyle({
            weight: 1,
            opacity: 0.3,
            color: 'gray'
        });
    });
}

// 重置高亮交圆 (移除 stopRotationAnimation 调用)
function resetHighlightedIntersectionCircles() {
    intersectionCircles.forEach(circle => {
        circle.setStyle(defaultIntersectionStyle);
    });
}

// 计算两点之间的距离（km）
function getDistanceFromLatLonInKm(lat1, lon1, lat2, lon2) {
    const R = 6371; // 地球半径（km）
    const dLat = deg2rad(lat2 - lat1);
    const dLon = deg2rad(lon2 - lon1);
    const a = 
        Math.sin(dLat/2) * Math.sin(dLat/2) +
        Math.cos(deg2rad(lat1)) * Math.cos(deg2rad(lat2)) * 
        Math.sin(dLon/2) * Math.sin(dLon/2); 
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a)); 
    const d = R * c; // 距离（km）
    return d;
}

// 度转弧度
function deg2rad(deg) {
    return deg * (Math.PI/180);
}

// 设置控件事件监听器
function setupControls() {
    document.getElementById('show-probes').addEventListener('change', renderMapElements);
    document.getElementById('show-predictions').addEventListener('change', renderMapElements);
    document.getElementById('show-actuals').addEventListener('change', renderMapElements);
    document.getElementById('show-lines').addEventListener('change', renderMapElements);
    document.getElementById('show-circles').addEventListener('change', toggleCircles);
    document.getElementById('show-intersection').addEventListener('change', toggleIntersectionArea);
    document.getElementById('show-selected-only').addEventListener('change', renderMapElements);
    
    // 交圆缩放控制器
    const circleScaleSlider = document.getElementById('circle-scale');
    const circleScaleValue = document.getElementById('circle-scale-value');
    
    circleScaleSlider.addEventListener('input', function() {
        circleScaleFactor = parseFloat(this.value);
        circleScaleValue.textContent = circleScaleFactor.toFixed(1);
        
        // 如果当前有显示交圆，则重新绘制
        if (currentLockedIndex !== null && document.getElementById('show-circles').checked) {
            const point = data.predicted[currentLockedIndex];
            showIntersectionCirclesForIP(point.ip);
        }
    });
}

// 切换交圆显示
function toggleCircles() {
    console.log('toggleCircles called. currentLockedIndex:', currentLockedIndex); // 新增日志
    const showCircles = document.getElementById('show-circles').checked;
    console.log('showCircles checkbox is:', showCircles); // 新增日志
    
    // 如果当前有选中的点，而且选项是显示交圆
    if (currentLockedIndex !== null && showCircles) {
        console.log('Condition 1: Showing circles for locked IP'); // 新增日志
        const point = data.predicted[currentLockedIndex];
        showIntersectionCirclesForIP(point.ip);
    } else if (showCircles && currentLockedIndex === null) {
        console.log('Condition 2: showCircles is true, but no locked IP'); // 新增日志
        // 如果勾选了显示交圆，但没有选中的点，显示提示信息
        updateHoverInfo('请先点击一个预测位置或实际位置，然后才能显示对应的交圆');
        // 确保清除所有交圆
        clearIntersectionCircles();
    } else if (!showCircles) {
        console.log('Condition 3: showCircles is false, clearing circles'); // 新增日志
        // 如果不显示交圆，则清除所有交圆
        clearIntersectionCircles();
    } else {
        console.log('toggleCircles: No condition met?'); // 新增日志，理论上不应执行
    }
}

// 切换交集区域显示
function toggleIntersectionArea() {
    console.log('toggleIntersectionArea called. currentLockedIndex:', currentLockedIndex);
    const showIntersectionArea = document.getElementById('show-intersection').checked;
    console.log('showIntersectionArea checkbox is:', showIntersectionArea);
    
    // 判断是否为Octant方法
    const isOctantMethod = currentDatasetId === 'octant' || currentDatasetId.startsWith('octant_');
    
    if (!isOctantMethod) {
        // 如果不是Octant方法，显示提示并取消勾选
        updateHoverInfo('交集区域功能仅适用于Octant环形方法');
        document.getElementById('show-intersection').checked = false;
        clearIntersectionAreas();
        return;
    }
    
    // 如果当前有选中的点，而且选项是显示交集区域
    if (currentLockedIndex !== null && showIntersectionArea) {
        console.log('Condition 1: Showing intersection area for locked IP');
        const point = data.predicted[currentLockedIndex];
        showIntersectionAreaForIP(point.ip);
    } else if (showIntersectionArea && currentLockedIndex === null) {
        console.log('Condition 2: showIntersectionArea is true, but no locked IP');
        // 如果勾选了显示交集区域，但没有选中的点，显示提示信息
        updateHoverInfo('请先点击一个预测位置或实际位置，然后才能显示对应的交集区域');
        // 确保清除所有交集区域
        clearIntersectionAreas();
    } else if (!showIntersectionArea) {
        console.log('Condition 3: showIntersectionArea is false, clearing areas');
        // 如果不显示交集区域，则清除所有交集区域
        clearIntersectionAreas();
    } else {
        console.log('toggleIntersectionArea: No condition met?');
    }
}

// 更新悬停信息面板
function updateHoverInfo(text) {
    if (!isDetailFixed) {
        document.getElementById('hover-info').innerHTML = text;
    }
}

// 重置悬停信息面板
function resetHoverInfo() {
    if (!isDetailFixed) {
        document.getElementById('hover-info').textContent = '鼠标悬停在元素上查看详情';
    }
}

// 停止所有圆形的动画 (简化，移除 circleAnimations 和 stroke-dashoffset 相关代码)
function stopAllAnimations() {
    // 重置所有交圆样式
    intersectionCircles.forEach(circle => {
        circle.setStyle(defaultIntersectionStyle);
    });
}

// 重置所有高亮标记
function resetHighlightedMarkers() {
    // 重置预测位置标记
    predictedMarkers.forEach(marker => {
        marker.setIcon(icons.predicted);
    });
    
    // 重置实际位置标记
    actualMarkers.forEach(marker => {
        marker.setIcon(icons.actual);
    });
    
    // 重置探针高亮状态
    resetProbeHighlights();
}

// 高亮指定索引的标记
function highlightMarkers(index) {
    if (index !== null && index >= 0 && index < predictedMarkers.length) {
        const predictedMarker = predictedMarkers[index];
        const actualMarker = actualMarkers[index];
        
        // 设置高亮图标
        predictedMarker.setIcon(icons.predictedHighlight);
        actualMarker.setIcon(icons.actualHighlight);
        
        // 确保高亮标记在最上层
        predictedMarker.setZIndexOffset(1000);
        actualMarker.setZIndexOffset(1000);
        
        // 高亮连接线
        highlightConnection(index);
    }
}

function setupCustomZoomControls() {
    const zoomInBtn = document.getElementById('zoom-in-btn');
    const zoomOutBtn = document.getElementById('zoom-out-btn');
    const zoomSlider = document.getElementById('zoom-slider');

    // 初始化滑块的值为当前地图的缩放级别
    // 滑块的 min/max 已在HTML中根据地图的 min/maxZoom 设置
    zoomSlider.min = map.getMinZoom();
    zoomSlider.max = map.getMaxZoom();
    zoomSlider.value = map.getZoom();
    zoomSlider.step = 0.5; // 设置滑动条的步长

    zoomInBtn.addEventListener('click', () => {
        map.setZoom(Math.min(map.getMaxZoom(), map.getZoom() + 0.5)); // 步长0.5
    });

    zoomOutBtn.addEventListener('click', () => {
        map.setZoom(Math.max(map.getMinZoom(), map.getZoom() - 0.5)); // 步长0.5
    });

    zoomSlider.addEventListener('input', (e) => {
        map.setZoom(parseFloat(e.target.value)); // 使用parseFloat因为step可能是小数
    });

    map.on('zoomend', () => {
        zoomSlider.value = map.getZoom();
    });
}

// 加载性能数据
async function loadPerformanceData() {
    try {
        // 不传递具体的数据集ID，让后端扫描所有可用的数据集
        const response = await fetch('/api/performance');
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        performanceData = await response.json();
        console.log('性能数据加载成功:', performanceData);
        console.log('发现的方法:', Object.keys(performanceData));
        
        // 更新界面
        updateMethodCheckboxes();
        updatePerformanceDisplay();
        
    } catch (error) {
        console.error('加载性能数据失败:', error);
        
        // 显示错误消息
        const metricsTable = document.getElementById('metrics-table');
        if (metricsTable) {
            metricsTable.innerHTML = '<p>加载性能数据失败，请检查数据文件是否存在。</p>';
        }
    }
}

// 获取当前数据集ID
function getCurrentDataset() {
    const datasetSelect = document.getElementById('dataset-select');
    return datasetSelect ? datasetSelect.value : '1_3';
}

// 更新方法复选框
function updateMethodCheckboxes() {
    const container = document.getElementById('method-checkboxes');
    if (!container) return;
    
    container.innerHTML = '';
    
    // 为每个可用的方法创建复选框
    Object.keys(performanceData).forEach(methodName => {
        if (performanceData[methodName] && performanceData[methodName].count > 0) {
            const label = document.createElement('label');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = methodName;
            checkbox.checked = true; // 默认全部选中
            checkbox.addEventListener('change', updatePerformanceDisplay);
            
            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(methodName));
            container.appendChild(label);
        }
    });
}

// 更新性能显示
function updatePerformanceDisplay() {
    updateMetricsTable();
    updateCDFChart();
}

// 更新指标表格
function updateMetricsTable() {
    const container = document.getElementById('metrics-table');
    if (!container) return;
    
    // 获取选中的方法
    const selectedMethods = getSelectedMethods();
    
    if (selectedMethods.length === 0) {
        container.innerHTML = '<p>请选择至少一种方法进行对比</p>';
        return;
    }
    
    // 创建表格
    const table = document.createElement('table');
    
    // 表头
    const headerRow = document.createElement('tr');
    headerRow.innerHTML = `
        <th>方法</th>
        <th>有效样本数</th>
        <th>总样本数</th>
        <th>均方根误差 (RMSE)</th>
        <th>平均绝对误差 (MAE)</th>
        <th>中位误差 (Median)</th>
    `;
    table.appendChild(headerRow);
    
    // 数据行
    selectedMethods.forEach(methodName => {
        const data = performanceData[methodName];
        if (data) {
            const validPercent = ((data.count / data.totalSamples) * 100).toFixed(1);
            const row = document.createElement('tr');
            row.innerHTML = `
                <td><strong>${methodName}</strong></td>
                <td>${data.count} (${validPercent}%)</td>
                <td>${data.totalSamples}</td>
                <td>${data.rmse !== null ? data.rmse + ' km' : 'N/A'}</td>
                <td>${data.mae !== null ? data.mae + ' km' : 'N/A'}</td>
                <td>${data.median !== null ? data.median + ' km' : 'N/A'}</td>
            `;
            table.appendChild(row);
        }
    });
    
    container.innerHTML = '';
    container.appendChild(table);
}

// 获取选中的方法
function getSelectedMethods() {
    const checkboxes = document.querySelectorAll('#method-checkboxes input[type="checkbox"]:checked');
    return Array.from(checkboxes).map(cb => cb.value);
}

// 更新CDF图表
function updateCDFChart() {
    const canvas = document.getElementById('cdf-chart');
    if (!canvas) return;
    
    // 获取选中的方法
    const selectedMethods = getSelectedMethods();
    
    if (selectedMethods.length === 0) {
        if (cdfChart) {
            // 清理自定义tooltip
            cleanupCustomTooltip();
            cdfChart.destroy();
            cdfChart = null;
        }
        return;
    }
    
    // 获取坐标轴控制值
    const xAxisMaxInput = document.getElementById('x-axis-max');
    const xAxisMinInput = document.getElementById('x-axis-min');
    
    let xAxisMax = null;
    let xAxisMin = 0;
    
    if (xAxisMaxInput && xAxisMaxInput.value !== 'auto' && xAxisMaxInput.value !== '') {
        xAxisMax = parseFloat(xAxisMaxInput.value);
    }
    
    if (xAxisMinInput && xAxisMinInput.value !== '') {
        xAxisMin = parseFloat(xAxisMinInput.value);
    }
    
    // 如果没有设置最大值，自动计算
    if (xAxisMax === null) {
        xAxisMax = 0;
        selectedMethods.forEach(methodName => {
            const data = performanceData[methodName];
            if (data && data.cdf && data.cdf.length > 0) {
                const maxAccuracy = Math.max(...data.cdf.map(point => point.accuracy));
                xAxisMax = Math.max(xAxisMax, maxAccuracy);
            }
        });
        // 在自动计算的基础上增加一些边距
        xAxisMax = Math.ceil(xAxisMax * 1.1);
    }
    
    // 准备图表数据 - 增加更多颜色选项
    const datasets = [];
    const colors = [
        '#FF6384', '#36A2EB', '#FFCE56', '#4BC0C0', '#9966FF', '#FF9F40',
        '#FF5722', '#4CAF50', '#2196F3', '#FF9800', '#E91E63', '#9C27B0',
        '#795548', '#607D8B', '#8BC34A', '#FFC107', '#00BCD4', '#3F51B5'
    ];
    
    selectedMethods.forEach((methodName, index) => {
        const data = performanceData[methodName];
        if (data && data.cdf && data.cdf.length > 0) {
            // 根据方法类型设置不同的线条样式
            let lineStyle = {};
            if (methodName.startsWith('CBG')) {
                lineStyle = { borderDash: [] }; // 实线
            } else if (methodName.startsWith('NCR+CBG')) {
                lineStyle = { borderDash: [10, 5] }; // 长虚线
            } else if (methodName.startsWith('NCR')) {
                lineStyle = { borderDash: [5, 5] }; // 中等虚线
            } else if (methodName.startsWith('Octant')) {
                lineStyle = { borderDash: [2, 3] }; // 短虚线
            }
            
            // 过滤数据点，只显示在坐标轴范围内的数据
            const filteredData = data.cdf
                .filter(point => point.accuracy >= xAxisMin && point.accuracy <= xAxisMax)
                .map(point => ({
                    x: point.accuracy,
                    y: point.percentage
                }));
            
            datasets.push({
                label: methodName,
                data: filteredData,
                borderColor: colors[index % colors.length],
                backgroundColor: colors[index % colors.length] + '20',
                fill: false,
                tension: 0.1,
                pointRadius: 0,
                pointHoverRadius: 5,
                borderWidth: 2,
                ...lineStyle
            });
        }
    });
    
    // 销毁旧图表
    if (cdfChart) {
        // 清理自定义tooltip
        cleanupCustomTooltip();
        cdfChart.destroy();
    }
    
    // 创建新图表
    const ctx = canvas.getContext('2d');
    cdfChart = new Chart(ctx, {
        type: 'line',
        data: {
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'linear',
                    position: 'bottom',
                    title: {
                        display: true,
                        text: '误差距离 (km)',
                        font: {
                            size: 12,
                            weight: 'bold'
                        }
                    },
                    min: xAxisMin,
                    max: xAxisMax,
                    grid: {
                        display: true,
                        color: 'rgba(0,0,0,0.1)'
                    }
                },
                y: {
                    title: {
                        display: true,
                        text: '累积百分比 (%)',
                        font: {
                            size: 12,
                            weight: 'bold'
                        }
                    },
                    min: 0,
                    max: 100,
                    grid: {
                        display: true,
                        color: 'rgba(0,0,0,0.1)'
                    }
                }
            },
            plugins: {
                title: {
                    display: false, // 隐藏图表标题，因为控制面板中已有标题
                    text: '累积分布函数 (CDF) - 定位误差对比',
                    font: {
                        size: 16,
                        weight: 'bold'
                    },
                    padding: 20
                },
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        pointStyle: 'line',
                        font: {
                            size: 11
                        },
                        generateLabels: function(chart) {
                            const original = Chart.defaults.plugins.legend.labels.generateLabels;
                            const labels = original.call(this, chart);
                            
                            // 添加线型样式信息
                            labels.forEach((label, index) => {
                                const dataset = chart.data.datasets[index];
                                if (dataset.borderDash && dataset.borderDash.length > 0) {
                                    label.lineDash = dataset.borderDash;
                                }
                            });
                            
                            return labels;
                        }
                    }
                },
                tooltip: {
                    enabled: false, // 禁用默认tooltip
                    external: function(context) {
                        // 自定义tooltip实现
                        const chart = context.chart;
                        const tooltip = context.tooltip;
                        
                        // 获取或创建tooltip元素
                        let tooltipEl = document.getElementById('chartjs-tooltip');
                        if (!tooltipEl) {
                            tooltipEl = document.createElement('div');
                            tooltipEl.id = 'chartjs-tooltip';
                            tooltipEl.style.cssText = `
                                position: absolute;
                                background: rgba(0, 0, 0, 0.9);
                                color: white;
                                border-radius: 6px;
                                pointer-events: none;
                                transform: translate(-50%, -100%);
                                padding: 12px;
                                font-size: 12px;
                                line-height: 1.4;
                                box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
                                z-index: 1000;
                                max-width: 300px;
                                border: 1px solid rgba(255, 255, 255, 0.2);
                            `;
                            document.body.appendChild(tooltipEl);
                        }
                        
                        // 隐藏tooltip
                        if (tooltip.opacity === 0) {
                            tooltipEl.style.opacity = '0';
                            return;
                        }
                        
                        // 如果有数据点，显示多曲线信息
                        if (tooltip.dataPoints && tooltip.dataPoints.length > 0) {
                            const xValue = tooltip.dataPoints[0].parsed.x;
                            
                            // 创建tooltip内容
                            let html = `<div style="font-weight: bold; margin-bottom: 8px; border-bottom: 1px solid rgba(255,255,255,0.3); padding-bottom: 6px;">误差距离: ${xValue.toFixed(2)} km</div>`;
                            
                            // 为每条曲线显示对应的y值
                            chart.data.datasets.forEach((dataset, index) => {
                                const data = dataset.data;
                                if (data && data.length > 0) {
                                    // 找到最接近当前x值的数据点
                                    let closestPoint = data[0];
                                    let minDistance = Math.abs(data[0].x - xValue);
                                    
                                    for (let i = 1; i < data.length; i++) {
                                        const distance = Math.abs(data[i].x - xValue);
                                        if (distance < minDistance) {
                                            minDistance = distance;
                                            closestPoint = data[i];
                                        }
                                    }
                                    
                                    // 如果距离太远，进行插值
                                    let yValue = closestPoint.y;
                                    if (minDistance > 0.1) {
                                        // 找到x值两侧的点进行线性插值
                                        let leftPoint = null;
                                        let rightPoint = null;
                                        
                                        for (let i = 0; i < data.length - 1; i++) {
                                            if (data[i].x <= xValue && data[i + 1].x >= xValue) {
                                                leftPoint = data[i];
                                                rightPoint = data[i + 1];
                                                break;
                                            }
                                        }
                                        
                                        if (leftPoint && rightPoint && leftPoint.x !== rightPoint.x) {
                                            const ratio = (xValue - leftPoint.x) / (rightPoint.x - leftPoint.x);
                                            yValue = leftPoint.y + ratio * (rightPoint.y - leftPoint.y);
                                        }
                                    }
                                    
                                    html += `
                                        <div style="display: flex; align-items: center; margin: 4px 0;">
                                            <div style="width: 12px; height: 2px; background-color: ${dataset.borderColor}; margin-right: 8px; ${dataset.borderDash && dataset.borderDash.length > 0 ? 'background-image: repeating-linear-gradient(to right, ' + dataset.borderColor + ' 0px, ' + dataset.borderColor + ' 3px, transparent 3px, transparent 6px);' : ''}"></div>
                                            <span style="flex: 1;">${dataset.label}</span>
                                            <span style="font-weight: bold; margin-left: 12px;">${yValue.toFixed(1)}%</span>
                                        </div>
                                    `;
                                }
                            });
                            
                            tooltipEl.innerHTML = html;
                        }
                        
                        // 定位tooltip
                        const canvasRect = chart.canvas.getBoundingClientRect();
                        tooltipEl.style.left = canvasRect.left + tooltip.caretX + 'px';
                        tooltipEl.style.top = canvasRect.top + tooltip.caretY - 10 + 'px';
                        tooltipEl.style.opacity = '1';
                    }
                }
            },
            interaction: {
                mode: 'index',
                intersect: false,
                axis: 'x'
            },
            onHover: (event, activeElements, chart) => {
                // 绘制垂直虚线
                const canvasRect = chart.canvas.getBoundingClientRect();
                const x = event.native.clientX - canvasRect.left;
                
                // 清除之前的虚线并重绘
                chart.update('none');
                
                if (activeElements.length > 0 || (x >= chart.chartArea.left && x <= chart.chartArea.right)) {
                    const ctx = chart.ctx;
                    ctx.save();
                    
                    // 设置虚线样式
                    ctx.setLineDash([4, 4]);
                    ctx.strokeStyle = 'rgba(0, 0, 0, 0.4)';
                    ctx.lineWidth = 1;
                    
                    // 绘制垂直线
                    ctx.beginPath();
                    ctx.moveTo(x, chart.chartArea.top);
                    ctx.lineTo(x, chart.chartArea.bottom);
                    ctx.stroke();
                    ctx.restore();
                }
            }
        }
    });
}

// 初始化性能分析功能
function initializePerformanceAnalysis() {
    // 视图切换按钮事件
    const mapViewBtn = document.getElementById('view-map');
    const performanceViewBtn = document.getElementById('view-performance');
    const mapView = document.getElementById('map-view');
    const performanceView = document.getElementById('performance-view');
    
    // 地图视图按钮点击事件
    mapViewBtn.addEventListener('click', () => {
        if (!mapViewBtn.classList.contains('active')) {
            // 切换到地图视图
            mapViewBtn.classList.add('active');
            performanceViewBtn.classList.remove('active');
            mapView.style.display = 'block';
            performanceView.style.display = 'none';
            
            // 清理自定义tooltip
            cleanupCustomTooltip();
            
            // 销毁性能分析图表释放资源
            if (cdfChart) {
                cdfChart.destroy();
                cdfChart = null;
            }
            
            // 重新调整地图大小
            setTimeout(() => {
                if (map) {
                    map.invalidateSize();
                }
            }, 100);
        }
    });
    
    // 性能分析视图按钮点击事件
    performanceViewBtn.addEventListener('click', () => {
        if (!performanceViewBtn.classList.contains('active')) {
            // 切换到性能分析视图
            performanceViewBtn.classList.add('active');
            mapViewBtn.classList.remove('active');
            performanceView.style.display = 'block';
            mapView.style.display = 'none';
            
            // 加载性能数据并显示
            loadPerformanceData();
        }
    });
    
    // 性能分析控制按钮事件
    const refreshBtn = document.getElementById('refresh-performance');
    const selectAllBtn = document.getElementById('select-all-methods');
    const deselectAllBtn = document.getElementById('deselect-all-methods');
    
    if (refreshBtn) {
        refreshBtn.addEventListener('click', () => {
            loadPerformanceData();
        });
    }
    
    if (selectAllBtn) {
        selectAllBtn.addEventListener('click', () => {
            const checkboxes = document.querySelectorAll('#method-checkboxes input[type="checkbox"]');
            checkboxes.forEach(cb => {
                cb.checked = true;
            });
            updatePerformanceDisplay();
        });
    }
    
    if (deselectAllBtn) {
        deselectAllBtn.addEventListener('click', () => {
            const checkboxes = document.querySelectorAll('#method-checkboxes input[type="checkbox"]');
            checkboxes.forEach(cb => {
                cb.checked = false;
            });
            updatePerformanceDisplay();
        });
    }
    
    // 初始化拖拽调整功能
    initializeResizer();
    
    // 初始化坐标轴控制
    initializeAxisControls();
}

// 清理自定义tooltip
function cleanupCustomTooltip() {
    const tooltipEl = document.getElementById('chartjs-tooltip');
    if (tooltipEl) {
        tooltipEl.remove();
    }
}

// 初始化拖拽调整功能
function initializeResizer() {
    const resizer = document.getElementById('chart-resizer');
    const chartSection = document.querySelector('.chart-section');
    const metricsSection = document.querySelector('.metrics-section');
    const performanceContent = document.querySelector('.performance-main-content');
    
    if (!resizer || !chartSection || !metricsSection || !performanceContent) {
        return;
    }
    
    let isResizing = false;
    let startX = 0;
    let startChartWidth = 0;
    let startMetricsWidth = 0;
    
    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        
        const chartRect = chartSection.getBoundingClientRect();
        const metricsRect = metricsSection.getBoundingClientRect();
        startChartWidth = chartRect.width;
        startMetricsWidth = metricsRect.width;
        
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
        
        e.preventDefault();
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        
        const deltaX = e.clientX - startX;
        const containerWidth = performanceContent.getBoundingClientRect().width - 6; // 减去分隔条宽度
        
        let newChartWidth = startChartWidth + deltaX;
        let newMetricsWidth = startMetricsWidth - deltaX;
        
        // 限制最小宽度
        const minChartWidth = 300;
        const minMetricsWidth = 250;
        
        if (newChartWidth < minChartWidth) {
            newChartWidth = minChartWidth;
            newMetricsWidth = containerWidth - newChartWidth;
        } else if (newMetricsWidth < minMetricsWidth) {
            newMetricsWidth = minMetricsWidth;
            newChartWidth = containerWidth - newMetricsWidth;
        }
        
        // 计算百分比
        const chartPercent = (newChartWidth / containerWidth) * 100;
        const metricsPercent = (newMetricsWidth / containerWidth) * 100;
        
        // 应用新的宽度
        chartSection.style.flex = `0 0 ${chartPercent}%`;
        metricsSection.style.flex = `0 0 ${metricsPercent}%`;
        
        // 通知Chart.js重新调整大小
        if (cdfChart) {
            setTimeout(() => {
                cdfChart.resize();
            }, 10);
        }
        
        e.preventDefault();
    });
    
    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
}

// 初始化坐标轴控制
function initializeAxisControls() {
    const xAxisMax = document.getElementById('x-axis-max');
    const xAxisMin = document.getElementById('x-axis-min');
    const resetAxisBtn = document.getElementById('reset-axis');
    
    if (!xAxisMax || !xAxisMin || !resetAxisBtn) {
        return;
    }
    
    // 坐标轴范围改变事件
    const updateChart = () => {
        if (cdfChart) {
            updateCDFChart();
        }
    };
    
    xAxisMax.addEventListener('change', updateChart);
    xAxisMax.addEventListener('input', updateChart);
    xAxisMin.addEventListener('change', updateChart);
    xAxisMin.addEventListener('input', updateChart);
    
    // 重置坐标轴按钮
    resetAxisBtn.addEventListener('click', () => {
        xAxisMax.value = 'auto';
        xAxisMin.value = '0';
        updateChart();
    });
}

// 查找并高亮形成交圆的探针
function highlightCircleProbes(ip) {
    if (!data.circles[ip]) {
        return;
    }
    
    // 获取该IP的所有交圆数据
    const circles = data.circles[ip];
    const tolerance = 0.001; // 坐标匹配容差（约100米）
    
    // 遍历每个圆形，找到对应的探针
    circles.forEach(circleData => {
        const circleCenter = circleData.center; // [lat, lng]
        
        // 在探针列表中查找匹配的探针
        probeMarkers.forEach(probeMarker => {
            const probePos = probeMarker.getLatLng();
            
            // 计算距离，如果足够接近就认为是同一个探针
            const distance = Math.sqrt(
                Math.pow(probePos.lat - circleCenter[0], 2) + 
                Math.pow(probePos.lng - circleCenter[1], 2)
            );
            
            if (distance < tolerance) {
                // 找到匹配的探针，将其图标改为紫色
                probeMarker.setIcon(icons.probeHighlight);
                // 标记该探针为高亮状态，方便后续重置
                probeMarker._originalIcon = icons.probe;
                probeMarker._isHighlighted = true;
                
                console.log(`高亮探针: ${probeMarker._probe?.id || '未知'} (圆心: [${circleCenter[0].toFixed(4)}, ${circleCenter[1].toFixed(4)}], RTT: ${circleData.rtt}ms)`);
            }
        });
    });
}

// 重置所有探针高亮状态
function resetProbeHighlights() {
    probeMarkers.forEach(probeMarker => {
        if (probeMarker._isHighlighted) {
            // 恢复原始图标
            probeMarker.setIcon(probeMarker._originalIcon || icons.probe);
            probeMarker._isHighlighted = false;
            delete probeMarker._originalIcon;
        }
    });
}

// 初始化
document.addEventListener('DOMContentLoaded', initMap); 