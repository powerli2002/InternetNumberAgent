const express = require('express');
const session = require('express-session');
const path = require('path');
const fs = require('fs');
const app = express();

// 读取配置文件
const config = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf8'));

// 扫描可用的数据集
function scanAvailableDatasets() {
    const outputDir = path.join(__dirname, '../../data/output');
    const datasets = [];
    
    try {
        const files = fs.readdirSync(outputDir);
        
        // 更新正则表达式以正确解析delta值（可能包含下划线）
        // 格式: user_result_loc_{method}_{delta}_{strategy}.json
        // method: cbg/ncr/cbgncr/octant
        // delta: 可能包含下划线，如1_3, 1_6, 0.398等
        // strategy: all/l3/d3/t3
        const resultLocPattern = /^user_result_loc_([^_]+)_(.+)_([^_]+)\.json$/;
        const circleMapPattern = /^user_circle_map_([^_]+)_(.+)_([^_]+)\.json$/;
        
        // 找出所有定位结果文件
        const resultFiles = files.filter(f => resultLocPattern.test(f));
        const circleFiles = files.filter(f => circleMapPattern.test(f));
        
        // 解析结果文件信息
        const datasetMap = new Map();
        
        resultFiles.forEach(fileName => {
            const match = fileName.match(resultLocPattern);
            if (match) {
                const [, method, deltaStrategy, lastPart] = match;
                
                // 重新解析delta和strategy，strategy应该是最后一个下划线后的部分
                const parts = deltaStrategy.split('_');
                const strategy = lastPart;
                const delta = parts.join('_');
                
                // 验证strategy是否合法
                const validStrategies = ['all', 'l3', 'd3', 't3'];
                if (validStrategies.includes(strategy)) {
                    const key = `${method}_${delta}_${strategy}`;
                    
                    if (!datasetMap.has(key)) {
                        datasetMap.set(key, {
                            method,
                            delta,
                            strategy,
                            resultFile: fileName,
                            circleFile: null
                        });
                    }
                }
            }
        });
        
        // 匹配对应的圆形文件
        circleFiles.forEach(fileName => {
            const match = fileName.match(circleMapPattern);
            if (match) {
                const [, method, deltaStrategy, lastPart] = match;
                
                // 重新解析delta和strategy
                const parts = deltaStrategy.split('_');
                const strategy = lastPart;
                const delta = parts.join('_');
                
                // 验证strategy是否合法
                const validStrategies = ['all', 'l3', 'd3', 't3'];
                if (validStrategies.includes(strategy)) {
                    const key = `${method}_${delta}_${strategy}`;
                    
                    if (datasetMap.has(key)) {
                        datasetMap.get(key).circleFile = fileName;
                    }
                }
            }
        });
        
        // 转换为数据集列表
        datasetMap.forEach((dataset, key) => {
            if (dataset.resultFile && dataset.circleFile) {
                // 按用户要求，直接显示方法后缀加注释
                const suffix = `${dataset.method}_${dataset.delta}_${dataset.strategy}`;
                const methodComment = getMethodComment(dataset.method);
                const deltaComment = getDeltaComment(dataset.delta);
                const strategyComment = getStrategyComment(dataset.strategy);
                
                datasets.push({
                    id: key,
                    name: `${suffix} (${methodComment}, δ=${deltaComment}, ${strategyComment})`,
                    method: dataset.method,
                    delta: dataset.delta,
                    strategy: dataset.strategy,
                    circleMapFile: dataset.circleFile,
                    resultLocFile: dataset.resultFile
                });
            }
        });
        
        // 兼容老格式的文件
        const legacyCircleMapFiles = files.filter(f => f.startsWith('user_circle_map_ori_') && f.endsWith('.json'));
        const legacyResultLocFiles = files.filter(f => f.startsWith('user_result_loc_ori_') && f.endsWith('.json'));
        
        // 提取文件的标识符部分
        const legacyCircleMapIds = legacyCircleMapFiles.map(f => f.replace('user_circle_map_ori_', '').replace('.json', ''));
        const legacyResultLocIds = legacyResultLocFiles.map(f => f.replace('user_result_loc_ori_', '').replace('.json', ''));
        
        // 找出同时存在circle_map和result_loc的老格式数据集
        const legacyCommonIds = legacyCircleMapIds.filter(id => legacyResultLocIds.includes(id));
        
        legacyCommonIds.forEach(id => {
            datasets.push({
                id: `legacy_${id}`,
                name: `cbg_ori_${id} (CBG传统格式, δ=${id}, 策略未知)`,
                method: 'cbg',
                delta: id,
                strategy: 'unknown',
                circleMapFile: `user_circle_map_ori_${id}.json`,
                resultLocFile: `user_result_loc_ori_${id}.json`
            });
        });
        
        // 按方法和参数排序
        datasets.sort((a, b) => {
            // 首先按方法排序
            const methodOrder = { 'cbg': 1, 'ncr': 2, 'cbgncr': 3, 'octant': 4 };
            const methodA = methodOrder[a.method] || 99;
            const methodB = methodOrder[b.method] || 99;
            
            if (methodA !== methodB) {
                return methodA - methodB;
            }
            
            // 然后按delta排序
            if (a.delta !== b.delta) {
                return a.delta.localeCompare(b.delta, undefined, {numeric: true});
            }
            
            // 最后按策略排序
            const strategyOrder = { 'all': 1, 'l3': 2, 'd3': 3, 't3': 4, 'unknown': 99 };
            const strategyA = strategyOrder[a.strategy] || 99;
            const strategyB = strategyOrder[b.strategy] || 99;
            
            return strategyA - strategyB;
        });
        
    } catch (error) {
        console.error('扫描数据集时出错:', error);
    }
    
    return datasets;
}

// 获取方法注释
function getMethodComment(method) {
    const methodComments = {
        'cbg': '交圆定位',
        'ncr': 'NCR方法',
        'cbgncr': 'CBG+NCR联合',
        'octant': '圆环定位'
    };
    return methodComments[method] || method.toUpperCase();
}

// 获取delta注释
function getDeltaComment(delta) {
    if (delta === 'default') {
        return '默认值';
    }
    // 将下划线转回分数形式用于显示
    if (delta.includes('_') && !delta.includes('.')) {
        return delta.replace('_', '/');
    }
    return delta;
}

// 获取策略注释
function getStrategyComment(strategy) {
    const strategyComments = {
        'all': '所有探针',
        'l3': '延迟最短3个探针',
        'd3': '距离最近3个探针',
        't3': '三角形包含策略',
        'unknown': '未知策略'
    };
    return strategyComments[strategy] || strategy;
}

// 中间件设置
app.use(express.json());
app.use(express.urlencoded({ extended: true }));

// 会话配置
app.use(session({
    secret: config.sessionSecret,
    resave: false,
    saveUninitialized: false,
    cookie: { 
        secure: false, // 在生产环境中应该设置为true（需要HTTPS）
        maxAge: 24 * 60 * 60 * 1000 // 24小时
    }
}));

// 身份验证中间件
function requireAuth(req, res, next) {
    if (req.session && req.session.authenticated) {
        return next();
    } else {
        return res.redirect('/login.html');
    }
}

// 登录API
app.post('/api/login', (req, res) => {
    const { username, password } = req.body;
    
    if (config.users[username] && config.users[username] === password) {
        req.session.authenticated = true;
        req.session.username = username;
        res.json({ success: true, message: '登录成功' });
    } else {
        res.status(401).json({ error: '用户名或密码错误' });
    }
});

// 登出API
app.post('/api/logout', (req, res) => {
    req.session.destroy((err) => {
        if (err) {
            res.status(500).json({ error: '登出失败' });
        } else {
            res.json({ success: true, message: '登出成功' });
        }
    });
});

// 获取可用数据集API
app.get('/api/datasets', requireAuth, (req, res) => {
    try {
        // 每次请求都重新扫描可用的数据集
        const datasets = scanAvailableDatasets();
        
        // 在响应头中添加禁止缓存的指令
        res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate');
        res.setHeader('Pragma', 'no-cache');
        res.setHeader('Expires', '0');
        
        res.json(datasets);
    } catch (error) {
        console.error('获取数据集列表失败:', error);
        res.status(500).json({ error: '获取数据集列表失败' });
    }
});

// 静态文件服务 - 登录页面不需要验证
app.get('/login.html', (req, res) => {
    res.sendFile(path.join(__dirname, 'login.html'));
});

app.get('/login-styles.css', (req, res) => {
    res.sendFile(path.join(__dirname, 'login-styles.css'));
});

// 设置静态文件目录，只暴露除server.js、package.json和config.json之外的文件
app.use((req, res, next) => {
    if (req.path.endsWith('server.js') || req.path.endsWith('package.json') || req.path.endsWith('config.json')) {
        res.status(403).send('Access Forbidden');
    } else {
        next();
    }
});

// 主页面需要身份验证
app.get('/', requireAuth, (req, res) => {
    res.sendFile(path.join(__dirname, 'index.html'));
});

// 其他静态文件也需要身份验证
app.use(requireAuth, express.static(__dirname, {
    index: false // 禁用默认index，因为我们已经在上面处理了
}));

// 动态数据加载API - 根据数据集ID加载对应的数据
app.get('/api/data/user_result_loc/:datasetId?', requireAuth, (req, res) => {
    try {
        const datasetId = req.params.datasetId || 'cbg_default_all'; // 默认数据集
        let filePath;
        
        // 解析数据集ID，支持新格式和老格式
        if (datasetId.startsWith('legacy_')) {
            // 老格式：legacy_1_3 -> user_result_loc_ori_1_3.json
            const suffix = datasetId.replace('legacy_', '');
            filePath = path.join(__dirname, `../../data/output/user_result_loc_ori_${suffix}.json`);
        } else {
            // 新格式：cbg_1_3_all -> user_result_loc_cbg_1_3_all.json
            // 或者兼容的格式判断
            if (datasetId.includes('_')) {
                // 尝试按新格式解析
                const parts = datasetId.split('_');
                if (parts.length >= 3) {
                    // 新格式
                    filePath = path.join(__dirname, `../../data/output/user_result_loc_${datasetId}.json`);
                } else {
                    // 可能是老格式的简化版本
                    filePath = path.join(__dirname, `../../data/output/user_result_loc_ori_${datasetId}.json`);
                }
            } else {
                // 单个标识符，尝试老格式
                filePath = path.join(__dirname, `../../data/output/user_result_loc_ori_${datasetId}.json`);
            }
        }
        
        // 如果文件不存在，尝试其他可能的路径
        if (!fs.existsSync(filePath)) {
            // 尝试直接使用数据集ID作为文件名
            const alternativePath = path.join(__dirname, `../../data/output/${datasetId}.json`);
            if (fs.existsSync(alternativePath)) {
                filePath = alternativePath;
            } else {
                return res.status(404).json({ error: `数据文件不存在: ${datasetId}` });
            }
        }
        
        // 使用fs.readFileSync替代require，避免缓存问题
        const fileContent = fs.readFileSync(filePath, 'utf8');
        const data = JSON.parse(fileContent);
        
        // 在响应头中添加禁止缓存的指令
        res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate');
        res.setHeader('Pragma', 'no-cache');
        res.setHeader('Expires', '0');
        
        res.json(data);
    } catch (error) {
        console.error(`加载数据失败: ${error.message}`);
        res.status(500).json({ error: `无法加载数据: ${error.message}` });
    }
});

app.get('/api/data/user_probes', requireAuth, (req, res) => {
    try {
        const filePath = path.join(__dirname, '../../data/format/user_probes.json');
        
        if (!fs.existsSync(filePath)) {
            return res.status(404).json({ error: '探针数据文件不存在' });
        }
        
        // 使用fs.readFileSync替代require，避免缓存问题
        const fileContent = fs.readFileSync(filePath, 'utf8');
        const data = JSON.parse(fileContent);
        
        // 在响应头中添加禁止缓存的指令
        res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate');
        res.setHeader('Pragma', 'no-cache');
        res.setHeader('Expires', '0');
        
        res.json(data);
    } catch (error) {
        console.error(`加载探针数据失败: ${error.message}`);
        res.status(500).json({ error: `无法加载探针数据: ${error.message}` });
    }
});

app.get('/api/data/user_circle_map/:datasetId?', requireAuth, (req, res) => {
    try {
        const datasetId = req.params.datasetId || 'cbg_default_all'; // 默认数据集
        let filePath;
        
        // 解析数据集ID，支持新格式和老格式
        if (datasetId.startsWith('legacy_')) {
            // 老格式：legacy_1_3 -> user_circle_map_ori_1_3.json
            const suffix = datasetId.replace('legacy_', '');
            filePath = path.join(__dirname, `../../data/output/user_circle_map_ori_${suffix}.json`);
        } else {
            // 新格式：cbg_1_3_all -> user_circle_map_cbg_1_3_all.json
            if (datasetId.includes('_')) {
                const parts = datasetId.split('_');
                if (parts.length >= 3) {
                    // 新格式
                    filePath = path.join(__dirname, `../../data/output/user_circle_map_${datasetId}.json`);
                } else {
                    // 可能是老格式的简化版本
                    filePath = path.join(__dirname, `../../data/output/user_circle_map_ori_${datasetId}.json`);
                }
            } else {
                // 单个标识符，尝试老格式
                filePath = path.join(__dirname, `../../data/output/user_circle_map_ori_${datasetId}.json`);
            }
        }
        
        // 如果文件不存在，尝试其他可能的路径
        if (!fs.existsSync(filePath)) {
            // 尝试直接使用数据集ID作为文件名
            const alternativePath = path.join(__dirname, `../../data/output/${datasetId}.json`);
            if (fs.existsSync(alternativePath)) {
                filePath = alternativePath;
            } else {
                return res.status(404).json({ error: `数据文件不存在: ${datasetId}` });
            }
        }
        
        // 使用fs.readFileSync替代require，避免缓存问题
        const fileContent = fs.readFileSync(filePath, 'utf8');
        const data = JSON.parse(fileContent);
        
        // 在响应头中添加禁止缓存的指令
        res.setHeader('Cache-Control', 'no-store, no-cache, must-revalidate, proxy-revalidate');
        res.setHeader('Pragma', 'no-cache');
        res.setHeader('Expires', '0');
        
        res.json(data);
    } catch (error) {
        console.error(`加载数据失败: ${error.message}`);
        res.status(500).json({ error: `无法加载数据: ${error.message}` });
    }
});

// 性能分析API
app.get('/api/performance/:datasetId?', requireAuth, (req, res) => {
    try {
        const outputDir = path.join(__dirname, '../../data/output');
        const performance = {};
        
        if (!fs.existsSync(outputDir)) {
            return res.status(404).json({ error: '输出目录不存在' });
        }
        
        // 扫描所有结果文件
        const files = fs.readdirSync(outputDir);
        
        // 更新正则表达式以正确解析delta值（可能包含下划线）
        const newFormatPattern = /^user_result_loc_([^_]+)_(.+)_([^_]+)\.json$/;
        
        // 扫描新格式的文件
        const newFormatFiles = files.filter(f => newFormatPattern.test(f));
        newFormatFiles.forEach(fileName => {
            const match = fileName.match(newFormatPattern);
            if (match) {
                const [, method, deltaStrategy, lastPart] = match;
                
                // 重新解析delta和strategy
                const parts = deltaStrategy.split('_');
                const strategy = lastPart;
                const delta = parts.join('_');
                
                // 验证strategy是否合法
                const validStrategies = ['all', 'l3', 'd3', 't3'];
                if (validStrategies.includes(strategy)) {
                    // 按用户要求的格式显示
                    const suffix = `${method}_${delta}_${strategy}`;
                    const methodComment = getMethodComment(method);
                    const deltaComment = getDeltaComment(delta);
                    const strategyComment = getStrategyComment(strategy);
                    const key = `${suffix} (${methodComment}, δ=${deltaComment}, ${strategyComment})`;
                    
                    try {
                        const filePath = path.join(outputDir, fileName);
                        const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
                        performance[key] = calculatePerformanceMetrics(data);
                    } catch (error) {
                        console.warn(`无法解析${key}数据: ${error.message}`);
                        performance[key] = null;
                    }
                }
            }
        });
        
        // 扫描老格式CBG方法的文件 (user_result_loc_ori_*.json)
        const legacyCbgFiles = files.filter(f => f.startsWith('user_result_loc_ori_') && f.endsWith('.json'));
        legacyCbgFiles.forEach(fileName => {
            const suffix = fileName.replace('user_result_loc_ori_', '').replace('.json', '');
            const key = `cbg_ori_${suffix} (CBG传统格式, δ=${suffix}, 策略未知)`;
            
            try {
                const filePath = path.join(outputDir, fileName);
                const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
                performance[key] = calculatePerformanceMetrics(data);
            } catch (error) {
                console.warn(`无法解析${key}数据: ${error.message}`);
                performance[key] = null;
            }
        });
        
        // 扫描其他老格式文件
        const legacyFiles = [
            { pattern: /^user_result_loc_ncr_(?!ori_).*\.json$/, prefix: 'user_result_loc_ncr_', method: 'NCR传统格式' },
            { pattern: /^user_result_loc_ncr_ori_.*\.json$/, prefix: 'user_result_loc_ncr_ori_', method: 'NCR+CBG传统格式' },
            { pattern: /^user_result_octant.*\.json$/, prefix: 'user_result_octant', method: 'Octant传统格式' }
        ];
        
        legacyFiles.forEach(({ pattern, prefix, method }) => {
            const matchingFiles = files.filter(f => pattern.test(f));
            matchingFiles.forEach(fileName => {
                let suffix = '';
                if (fileName === `${prefix}.json`) {
                    suffix = '默认';
                } else {
                    suffix = fileName.replace(prefix, '').replace('_', '').replace('.json', '');
                }
                
                const key = suffix ? `${method}_${suffix} (${method}, 参数=${suffix})` : `${method} (传统格式)`;
                
                try {
                    const filePath = path.join(outputDir, fileName);
                    const data = JSON.parse(fs.readFileSync(filePath, 'utf8'));
                    performance[key] = calculatePerformanceMetrics(data);
                } catch (error) {
                    console.warn(`无法解析${key}数据: ${error.message}`);
                    performance[key] = null;
                }
            });
        });
        
        // 过滤掉null值并按方法名排序
        const filteredPerformance = {};
        Object.keys(performance)
            .filter(key => performance[key] !== null && performance[key].count > 0)
            .sort((a, b) => {
                // 按方法类型排序：cbg < ncr < cbgncr < octant
                const getMethodOrder = (key) => {
                    if (key.includes('cbg_') && !key.includes('ncr')) return 1;
                    if (key.includes('ncr_') && !key.includes('cbg')) return 2;
                    if (key.includes('cbgncr_')) return 3;
                    if (key.includes('octant_')) return 4;
                    return 99; // 传统格式放后面
                };
                
                const orderA = getMethodOrder(a);
                const orderB = getMethodOrder(b);
                
                if (orderA !== orderB) {
                    return orderA - orderB;
                }
                
                // 同类型内按名称排序
                return a.localeCompare(b, undefined, {numeric: true});
            })
            .forEach(key => {
                filteredPerformance[key] = performance[key];
            });
        
        console.log(`发现 ${Object.keys(filteredPerformance).length} 个有效的性能数据集:`, Object.keys(filteredPerformance));
        
        res.json(filteredPerformance);
    } catch (error) {
        console.error(`性能分析失败: ${error.message}`);
        res.status(500).json({ error: `性能分析失败: ${error.message}` });
    }
});

// 计算性能指标的辅助函数
function calculatePerformanceMetrics(data) {
    if (!data || !Array.isArray(data)) {
        return null;
    }
    
    const totalSamples = data.length;
    
    // 提取有效的误差数据
    const allErrors = data.map(item => {
        // 支持不同的数据格式
        if (Array.isArray(item) && item.length > 1) {
            return item[1]; // error在第2个位置
        } else if (typeof item === 'object' && item.error !== undefined) {
            return item.error;
        }
        return null;
    });
    
    // 分析数据质量
    const nullErrors = allErrors.filter(error => error === null || error === undefined).length;
    const nanErrors = allErrors.filter(error => error !== null && error !== undefined && isNaN(error)).length;
    const negativeErrors = allErrors.filter(error => error !== null && error !== undefined && !isNaN(error) && error < 0).length;
    
    // 只保留有效数据
    const errors = allErrors.filter(error => error !== null && error !== undefined && !isNaN(error) && error >= 0);
    
    if (errors.length === 0) {
        return {
            count: 0,
            totalSamples: totalSamples,
            invalidSamples: totalSamples,
            nullErrors: nullErrors,
            nanErrors: nanErrors,
            negativeErrors: negativeErrors,
            rmse: null,
            mae: null,
            median: null,
            p50: null,
            p95: null,
            cdf_objective: 1.0,
            normalized_area_under_cdf: 0.0,
            cdf: []
        };
    }
    
    // 排序误差数据
    const sortedErrors = [...errors].sort((a, b) => a - b);
    
    // 计算RMSE (Root Mean Square Error)
    const mse = errors.reduce((sum, error) => sum + error * error, 0) / errors.length;
    const rmse = Math.sqrt(mse);
    
    // 计算MAE (Mean Absolute Error) - 与Python的mean_error_km一致
    const mae = errors.reduce((sum, error) => sum + error, 0) / errors.length;
    
    // 计算P50中位误差 - 使用与numpy.percentile相同的逻辑
    const p50 = calculatePercentile(sortedErrors, 50);
    
    // 计算P95误差
    const p95 = calculatePercentile(sortedErrors, 95);
    
    // 保持原有的median计算以向后兼容
    const median = sortedErrors.length % 2 === 0
        ? (sortedErrors[sortedErrors.length / 2 - 1] + sortedErrors[sortedErrors.length / 2]) / 2
        : sortedErrors[Math.floor(sortedErrors.length / 2)];
    
    // 计算归一化CDF面积 - 与Python逻辑一致
    const X_MAX_CDF = 8000.0; // 与Python代码中的X_MAX_CDF保持一致
    const normalizedAreaUnderCdf = calculateNormalizedAreaUnderCdf(sortedErrors, X_MAX_CDF);
    const cdfObjective = 1.0 - normalizedAreaUnderCdf;
    
    // 生成累积分布函数(CDF)数据 - 保持原有格式
    const maxError = Math.max(...sortedErrors);
    const minError = Math.min(...sortedErrors);
    const step = Math.max(0.1, (maxError - minError) / 100); // 至少100个数据点
    
    const cdf = [];
    for (let accuracy = 0; accuracy <= maxError + step; accuracy += step) {
        const count = sortedErrors.filter(error => error <= accuracy).length;
        const percentage = (count / sortedErrors.length) * 100;
        cdf.push({
            accuracy: parseFloat(accuracy.toFixed(2)),
            percentage: parseFloat(percentage.toFixed(2))
        });
    }
    
    return {
        count: errors.length,
        totalSamples: totalSamples,
        invalidSamples: totalSamples - errors.length,
        nullErrors: nullErrors,
        nanErrors: nanErrors,
        negativeErrors: negativeErrors,
        rmse: parseFloat(rmse.toFixed(3)),
        mae: parseFloat(mae.toFixed(3)),
        median: parseFloat(median.toFixed(3)),
        p50: parseFloat(p50.toFixed(3)),
        p95: parseFloat(p95.toFixed(3)),
        cdf_objective: parseFloat(cdfObjective.toFixed(6)),
        normalized_area_under_cdf: parseFloat(normalizedAreaUnderCdf.toFixed(6)),
        cdf: cdf
    };
}

// 计算百分位数 - 与numpy.percentile逻辑一致
function calculatePercentile(sortedArray, percentile) {
    if (sortedArray.length === 0) return 0;
    if (sortedArray.length === 1) return sortedArray[0];
    
    const index = (percentile / 100) * (sortedArray.length - 1);
    const lower = Math.floor(index);
    const upper = Math.ceil(index);
    
    if (lower === upper) {
        return sortedArray[lower];
    }
    
    const weight = index - lower;
    return sortedArray[lower] * (1 - weight) + sortedArray[upper] * weight;
}

// 计算CDF曲线下的归一化面积 - 与Python逻辑一致
function calculateNormalizedAreaUnderCdf(sortedErrors, xMaxCdf) {
    if (sortedErrors.length === 0) return 0.0;
    
    const n = sortedErrors.length;
    
    // 构建CDF曲线的点集
    const xCoords = [0.0];  // 从0开始
    const yCoords = [0.0];  // 对应的累积概率
    
    // 添加排序后的误差值和对应的累积概率
    for (let i = 0; i < sortedErrors.length; i++) {
        const error = sortedErrors[i];
        if (error <= xMaxCdf) {
            xCoords.push(error);
            yCoords.push((i + 1) / n);
        }
    }
    
    // 确保包含xMaxCdf这一点
    if (xCoords[xCoords.length - 1] < xMaxCdf) {
        // 找到在xMaxCdf处的累积概率
        const cumProbAtMax = sortedErrors.filter(e => e <= xMaxCdf).length / n;
        xCoords.push(xMaxCdf);
        yCoords.push(cumProbAtMax);
    }
    
    // 使用梯形法则计算CDF曲线下的面积
    const areaUnderCdf = trapezoidalRule(xCoords, yCoords);
    
    // 计算归一化面积
    const normalizedArea = areaUnderCdf / xMaxCdf;
    
    // 确保值在[0, 1]区间
    return Math.max(0.0, Math.min(1.0, normalizedArea));
}

// 梯形法则计算积分
function trapezoidalRule(xCoords, yCoords) {
    if (xCoords.length !== yCoords.length || xCoords.length < 2) {
        return 0.0;
    }
    
    let area = 0.0;
    for (let i = 1; i < xCoords.length; i++) {
        const dx = xCoords[i] - xCoords[i - 1];
        const avgY = (yCoords[i] + yCoords[i - 1]) / 2;
        area += dx * avgY;
    }
    
    return area;
}

const PORT = process.env.PORT || 8080;
app.listen(PORT, () => {
    console.log(`服务器运行在 http://localhost:${PORT}`);
    
    const datasets = scanAvailableDatasets();
    console.log(`发现 ${datasets.length} 个可用数据集:`);
    datasets.forEach(dataset => {
        console.log(`  - ${dataset.name} (ID: ${dataset.id})`);
    });
}); 