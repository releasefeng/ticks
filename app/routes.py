from flask import Blueprint, render_template, jsonify, request, flash, redirect, url_for, send_file
from flask_login import login_required, current_user
from app.models import LotteryDraw, UserPrediction, ManualImportData
from app import db
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from app.lottery_spider import LotterySpider
from collections import defaultdict, Counter
import io
import os
from itertools import combinations

main = Blueprint('main', __name__)

@main.route('/')
def index():
    latest_draws = LotteryDraw.query.order_by(LotteryDraw.draw_date.desc()).limit(10).all()
    return render_template('index.html', draws=latest_draws)

@main.route('/analysis', methods=['GET', 'POST'])
@login_required
def analysis():
    # 获取用户选择的筛选条件
    even_majority = request.form.get('even_majority', 'false').lower() == 'true'
    
    # 获取最近100期开奖数据
    draws = LotteryDraw.query.order_by(LotteryDraw.draw_date.desc()).limit(100).all()
    
    # 初始化频率统计
    front_freq = defaultdict(int)
    back_freq = defaultdict(int)
    
    # 记录每个号码最后出现的期数
    front_last_appear = defaultdict(int)
    back_last_appear = defaultdict(int)
    
    # 统计号码频率和组合
    draw_dates = []
    prize_amounts = []
    patterns = []
    
    for idx, draw in enumerate(draws):
        draw_dates.append(draw.draw_date.strftime('%Y-%m-%d'))
        prize_amounts.append(draw.first_prize_amount / 10000)  # 转换为万元
        
        front_nums = draw.numbers.split('+')[0].split(',')
        back_nums = draw.numbers.split('+')[1].split(',')
        
        # 更新频率统计
        for num in front_nums:
            front_freq[num] += 1
            if front_last_appear[num] == 0:
                front_last_appear[num] = idx
                
        for num in back_nums:
            back_freq[num] += 1
            if back_last_appear[num] == 0:
                back_last_appear[num] = idx
        
        # 分析号码组合模式
        pattern = analyze_number_pattern(front_nums, back_nums)
        patterns.append(pattern)
    
    # 预测下期最有可能出现的组合模式
    predicted_pattern = predict_next_pattern(patterns)
    
    # 计算平均频率
    front_avg_freq = sum(front_freq.values()) / len(front_freq) if front_freq else 0
    back_avg_freq = sum(back_freq.values()) / len(back_freq) if back_freq else 0
    
    # 获取热门号码（按频率排序）
    front_hot_numbers = sorted(front_freq.items(), key=lambda x: x[1], reverse=True)[:7]  # 前区取前7个
    back_hot_numbers = sorted(back_freq.items(), key=lambda x: x[1], reverse=True)[:5]   # 后区取前5个
    
    # 获取冷门号码（最近未出现的期数）
    cold_threshold = 10  # 定义冷门号码的阈值
    front_cold_numbers = []
    back_cold_numbers = []
    
    for num in [f"{i:02d}" for i in range(1, 36)]:
        if num not in front_freq:
            front_cold_numbers.append((num, 100))
        else:
            front_cold_numbers.append((num, front_last_appear[num]))
            
    for num in [f"{i:02d}" for i in range(1, 13)]:
        if num not in back_freq:
            back_cold_numbers.append((num, 100))
        else:
            back_cold_numbers.append((num, back_last_appear[num]))
    
    front_cold_numbers.sort(key=lambda x: x[1], reverse=True)
    back_cold_numbers.sort(key=lambda x: x[1], reverse=True)
    
    # 只取前7个前区冷门号码和前5个后区冷门号码
    front_cold_numbers = front_cold_numbers[:7]
    back_cold_numbers = back_cold_numbers[:5]
    
    # 分析热门组合
    pattern_counter = Counter(patterns)
    popular_combos = [
        {
            'pattern': pattern,
            'count': count,
            'last_appear': draw_dates[patterns.index(pattern)]
        }
        for pattern, count in pattern_counter.most_common(5)
    ]
    
    # 从冷门号码中生成组合
    # 获取冷门号码列表
    front_cold_nums = [num for num, _ in front_cold_numbers]
    back_cold_nums = [num for num, _ in back_cold_numbers]
    
    # 生成所有可能的组合
    front_combinations = list(combinations(front_cold_nums, 5))
    back_combinations = list(combinations(back_cold_nums, 2))
    
    # 根据预测的模式筛选组合
    cold_combinations = []
    for f in front_combinations:
        for b in back_combinations:
            # 分析组合特征
            front = [int(x) for x in f]
            back = [int(x) for x in b]
            
            # 检查是否符合预测的模式
            pattern = analyze_number_pattern(f, b)
            
            # 如果用户选择了偶数多于奇数的条件，则进行相应检查
            if pattern == predicted_pattern and (not even_majority or is_even_majority(front)):
                cold_combinations.append({
                    'front': sorted(f),
                    'back': sorted(b),
                    'pattern': pattern,
                    'even_count': sum(1 for x in front if x % 2 == 0)
                })
    
    # 如果冷门组合为空，则显示所有可能的组合
    if not cold_combinations:
        for f in front_combinations:
            for b in back_combinations:
                front = [int(x) for x in f]
                if not even_majority or is_even_majority(front):
                    cold_combinations.append({
                        'front': sorted(f),
                        'back': sorted(b),
                        'pattern': analyze_number_pattern(f, b),
                        'even_count': sum(1 for x in front if x % 2 == 0)
                    })
    
    # 按偶数数量排序
    cold_combinations.sort(key=lambda x: x['even_count'], reverse=True)
    
    # 计算冷门号码统计
    front_cold_stats = calculate_cold_number_stats(draws, front_cold_numbers[:5], 'front')
    back_cold_stats = calculate_cold_number_stats(draws, back_cold_numbers[:3], 'back')
    
    # 计算冷门号码组合的历史统计
    cold_combination_stats = calculate_cold_combination_stats(draws, front_cold_numbers, back_cold_numbers)
    
    # 生成数据分析建议
    analysis_suggestions = {
        'hot_numbers': {
            'front': [num for num, _ in front_hot_numbers],
            'back': [num for num, _ in back_hot_numbers]
        },
        'cold_numbers': {
            'front': [num for num, _ in front_cold_numbers],
            'back': [num for num, _ in back_cold_numbers]
        },
        'cold_stats': {
            'front': front_cold_stats,
            'back': back_cold_stats
        },
        'cold_combination_stats': cold_combination_stats,
        'pattern_analysis': f"预测下期最有可能出现的组合模式是：{predicted_pattern}" + 
                          ("，且前区偶数多于奇数" if even_majority else ""),
        'cold_combinations': cold_combinations[:20],  # 显示前20个组合
        'even_majority': even_majority  # 添加筛选条件状态
    }
    
    # 反转日期和奖金列表，使其按时间顺序显示
    draw_dates.reverse()
    prize_amounts.reverse()
    
    return render_template('analysis.html',
        front_freq=front_freq,
        back_freq=back_freq,
        front_avg_freq=front_avg_freq,
        back_avg_freq=back_avg_freq,
        front_hot_numbers=front_hot_numbers,
        back_hot_numbers=back_hot_numbers,
        front_cold_numbers=front_cold_numbers,
        back_cold_numbers=back_cold_numbers,
        cold_threshold=cold_threshold,
        popular_combos=popular_combos,
        draw_dates=draw_dates,
        prize_amounts=prize_amounts,
        analysis_suggestions=analysis_suggestions
    )

def analyze_number_pattern(front_nums, back_nums):
    """分析号码组合模式"""
    # 将号码转换为整数进行分析
    front = [int(x) for x in front_nums]
    back = [int(x) for x in back_nums]
    
    # 分析前区特征
    front_features = []
    if max(front) - min(front) <= 10:
        front_features.append("连号")
    if sum(1 for x in front if x <= 17) >= 3:
        front_features.append("小号组")
    elif sum(1 for x in front if x > 17) >= 3:
        front_features.append("大号组")
    
    # 分析后区特征
    back_features = []
    if abs(back[0] - back[1]) <= 2:
        back_features.append("邻号")
    elif max(back) - min(back) >= 8:
        back_features.append("跨度大")
    
    # 组合特征
    front_pattern = "+".join(front_features) if front_features else "常规"
    back_pattern = "+".join(back_features) if back_features else "常规"
    
    return f"{front_pattern}/{back_pattern}"

def is_even_majority(numbers):
    """检查偶数是否多于奇数"""
    even_count = sum(1 for x in numbers if x % 2 == 0)
    return even_count > len(numbers) / 2

def predict_next_pattern(patterns):
    """预测下期最有可能出现的组合模式"""
    # 分析最近10期的模式变化趋势
    recent_patterns = patterns[:10]
    pattern_counter = Counter(recent_patterns)
    
    # 获取最近出现次数最多的模式
    most_recent_pattern = pattern_counter.most_common(1)[0][0]
    
    # 分析模式转换概率
    pattern_transitions = defaultdict(lambda: defaultdict(int))
    for i in range(len(patterns) - 1):
        current = patterns[i]
        next_pattern = patterns[i + 1]
        pattern_transitions[current][next_pattern] += 1
    
    # 计算从最近模式转换到其他模式的概率
    if most_recent_pattern in pattern_transitions:
        transitions = pattern_transitions[most_recent_pattern]
        total = sum(transitions.values())
        probabilities = {p: count/total for p, count in transitions.items()}
        # 选择概率最高的模式
        predicted_pattern = max(probabilities.items(), key=lambda x: x[1])[0]
    else:
        predicted_pattern = most_recent_pattern
    
    return predicted_pattern

def calculate_cold_number_stats(draws, cold_numbers, area='front'):
    """计算冷门号码的中奖概率和赔率"""
    stats = []
    
    for num, cold_periods in cold_numbers:
        # 统计该号码在最近100期中的出现次数
        appear_count = 0
        for draw in draws:
            if area == 'front':
                numbers = draw.numbers.split('+')[0].split(',')
            else:
                numbers = draw.numbers.split('+')[1].split(',')
            
            if num in numbers:
                appear_count += 1
        
        # 计算中奖概率
        probability = appear_count / len(draws)
        
        # 计算赔率（假设每注2元）
        if probability > 0:
            odds = 2 / probability
            odds_str = "%.2f" % odds
        else:
            odds_str = "∞"
        
        stats.append({
            'number': num,
            'cold_periods': cold_periods,
            'probability': probability,
            'odds': odds_str
        })
    
    return stats

def calculate_cold_combination_stats(draws, front_cold_numbers, back_cold_numbers):
    """计算冷门号码组合的历史中奖情况和投资回报率"""
    # 获取冷门号码列表
    front_cold_nums = [num for num, _ in front_cold_numbers[:5]]
    back_cold_nums = [num for num, _ in back_cold_numbers[:3]]
    
    # 初始化统计
    total_investment = 0  # 总投入
    total_prize = 0       # 总奖金
    winning_count = 0     # 中奖次数
    
    # 遍历每期开奖结果
    for draw in draws:
        # 解析开奖号码
        front_winning = draw.numbers.split('+')[0].split(',')
        back_winning = draw.numbers.split('+')[1].split(',')
        
        # 计算当期投入（假设每注2元）
        investment = 2 * len(list(combinations(front_cold_nums, 5))) * len(list(combinations(back_cold_nums, 2)))
        total_investment += investment
        
        # 检查是否中奖
        is_winning = False
        prize = 0
        
        # 检查前区中奖情况
        front_matches = sum(1 for num in front_winning if num in front_cold_nums)
        back_matches = sum(1 for num in back_winning if num in back_cold_nums)
        
        # 根据中奖规则计算奖金（只使用前五等奖）
        if front_matches == 5 and back_matches == 2:
            prize = draw.first_prize_amount
            is_winning = True
        elif front_matches == 5 and back_matches == 1:
            prize = draw.second_prize_amount
            is_winning = True
        elif front_matches == 5 and back_matches == 0:
            prize = draw.third_prize_amount
            is_winning = True
        elif front_matches == 4 and back_matches == 2:
            prize = draw.fourth_prize_amount
            is_winning = True
        elif front_matches == 4 and back_matches == 1:
            prize = draw.fifth_prize_amount
            is_winning = True
        
        if is_winning:
            winning_count += 1
            total_prize += prize
    
    # 计算统计结果
    winning_rate = winning_count / len(draws) * 100
    roi = (total_prize - total_investment) / total_investment * 100 if total_investment > 0 else 0
    
    return {
        'winning_rate': winning_rate,
        'total_investment': total_investment,
        'total_prize': total_prize,
        'winning_count': winning_count,
        'roi': roi
    }

@main.route('/predict', methods=['GET', 'POST'])
@login_required
def predict():
    if request.method == 'POST':
        numbers = request.form.get('numbers')
        
        # 验证号码格式
        try:
            front_nums = [int(x) for x in numbers.split('+')[0].split(',')]
            back_nums = [int(x) for x in numbers.split('+')[1].split(',')]
            
            if len(front_nums) != 5 or len(back_nums) != 2:
                raise ValueError
            
            if not all(1 <= x <= 35 for x in front_nums) or not all(1 <= x <= 12 for x in back_nums):
                raise ValueError
            
        except (ValueError, IndexError):
            flash('号码格式错误，前区需要5个1-35的号码，后区需要2个1-12的号码')
            return redirect(url_for('main.predict'))
        
        prediction = UserPrediction(
            user_id=current_user.id,
            numbers=numbers
        )
        db.session.add(prediction)
        db.session.commit()
        
        flash('预测号码已保存')
        return redirect(url_for('main.predict'))
    
    user_predictions = UserPrediction.query.filter_by(user_id=current_user.id)\
        .order_by(UserPrediction.created_at.desc()).limit(10).all()
    return render_template('predict.html', predictions=user_predictions)

@main.route('/fetch-latest')
@login_required
def fetch_latest():
    spider = LotterySpider()
    success, message = spider.update_database()
    
    if success:
        flash('数据更新成功')
    else:
        flash(message)
    
    return redirect(url_for('main.index'))

@main.route('/statistics')
@login_required
def statistics():
    # 用户投注统计
    total_predictions = UserPrediction.query.filter_by(user_id=current_user.id).count()
    winning_predictions = UserPrediction.query.filter_by(user_id=current_user.id, is_hit=True).count()
    total_prize = db.session.query(db.func.sum(UserPrediction.prize_amount))\
        .filter_by(user_id=current_user.id).scalar() or 0
    
    stats = {
        'total_predictions': total_predictions,
        'winning_predictions': winning_predictions,
        'win_rate': (winning_predictions / total_predictions * 100) if total_predictions > 0 else 0,
        'total_prize': total_prize
    }
    
    return render_template('statistics.html', stats=stats)

@main.route('/feature-trend')
@login_required
def feature_trend():
    # 获取最近100期开奖数据
    draws = LotteryDraw.query.order_by(LotteryDraw.draw_date.desc()).limit(100).all()
    
    # 初始化数据存储
    draw_dates = []
    front_sums = []  # 前区号码和
    back_sums = []   # 后区号码和
    front_evens = [] # 前区偶数个数
    back_evens = []  # 后区偶数个数
    front_primes = [] # 前区质数个数
    back_primes = []  # 后区质数个数
    patterns = []     # 组合特征
    
    for draw in reversed(draws):  # 按时间顺序处理
        draw_dates.append(draw.draw_date.strftime('%Y-%m-%d'))
        
        # 解析号码
        front_nums = [int(x) for x in draw.numbers.split('+')[0].split(',')]
        back_nums = [int(x) for x in draw.numbers.split('+')[1].split(',')]
        
        # 计算特征
        front_sums.append(sum(front_nums))
        back_sums.append(sum(back_nums))
        front_evens.append(sum(1 for x in front_nums if x % 2 == 0))
        back_evens.append(sum(1 for x in back_nums if x % 2 == 0))
        
        # 质数判断函数
        def is_prime(n):
            if n < 2:
                return False
            for i in range(2, int(n**0.5) + 1):
                if n % i == 0:
                    return False
            return True
        
        front_primes.append(sum(1 for x in front_nums if is_prime(x)))
        back_primes.append(sum(1 for x in back_nums if is_prime(x)))
        
        # 分析组合特征
        front_pattern = []
        back_pattern = []
        
        # 前区特征分析
        if sum(1 for x in front_nums if x <= 17) >= 3:
            front_pattern.append("小号")
        elif sum(1 for x in front_nums if x > 17) >= 3:
            front_pattern.append("大号")
            
        if max(front_nums) - min(front_nums) <= 10:
            front_pattern.append("连号")
            
        # 后区特征分析
        if abs(back_nums[0] - back_nums[1]) <= 2:
            back_pattern.append("邻号")
        elif max(back_nums) - min(back_nums) >= 8:
            back_pattern.append("跨度大")
            
        # 组合特征
        front_str = "+".join(front_pattern) if front_pattern else "常规"
        back_str = "+".join(back_pattern) if back_pattern else "常规"
        pattern = f"{front_str}/{back_str}"
        patterns.append(pattern)
    
    # 分析组合特征出现频率
    pattern_counter = Counter(patterns)
    total_patterns = len(patterns)
    pattern_probabilities = {
        pattern: count / total_patterns 
        for pattern, count in pattern_counter.items()
    }
    
    # 预测下一期最可能的组合
    predicted_pattern = max(pattern_probabilities.items(), key=lambda x: x[1])[0]
    
    return render_template('feature_trend.html',
                         draw_dates=draw_dates,
                         front_sums=front_sums,
                         back_sums=back_sums,
                         front_evens=front_evens,
                         back_evens=back_evens,
                         front_primes=front_primes,
                         back_primes=back_primes,
                         pattern_probabilities=pattern_probabilities,
                         predicted_pattern=predicted_pattern)

@main.route('/fetch-historical')
@login_required
def fetch_historical():
    """手动获取历史数据"""
    try:
        spider = LotterySpider()
        historical_data = spider.fetch_historical_data(pages=5)  # 获取最近5页的数据
        
        for data in historical_data:
            existing = LotteryDraw.query.filter_by(draw_number=data['draw_number']).first()
            if not existing:
                new_draw = LotteryDraw(**data)
                db.session.add(new_draw)
        
        db.session.commit()
        flash(f'成功获取{len(historical_data)}期历史数据')
    except Exception as e:
        flash(f'获取历史数据失败：{str(e)}')
    
    return redirect(url_for('main.index'))

@main.route('/recommend', methods=['GET', 'POST'])
@login_required
def recommend():
    spider = LotterySpider()
    strategies = {
        'smart': '智能选号',
        'hot': '热门号码',
        'cold': '冷门号码',
        'balanced': '平衡选号',
        'random': '随机选号'
    }
    
    if request.method == 'POST':
        strategy = request.form.get('strategy', 'smart')
        num_suggestions = int(request.form.get('num_suggestions', 5))
        suggestions = spider.recommend_numbers(strategy, num_suggestions)
        return render_template('recommend.html',
            suggestions=suggestions,
            strategies=strategies,
            selected_strategy=strategy,
            num_suggestions=num_suggestions
        )
    
    # 默认显示智能选号的5注推荐
    suggestions = spider.recommend_numbers()
    return render_template('recommend.html',
        suggestions=suggestions,
        strategies=strategies,
        selected_strategy='smart',
        num_suggestions=5
    )

@main.route('/manual-data', methods=['GET', 'POST'])
@login_required
def manual_data():
    if request.method == 'POST':
        if 'file' not in request.files:
            flash('没有选择文件')
            return redirect(request.url)
        
        file = request.files['file']
        if file.filename == '':
            flash('没有选择文件')
            return redirect(request.url)
        
        if file and file.filename.endswith('.xlsx'):
            try:
                # 读取Excel文件
                df = pd.read_excel(file)
                
                # 验证数据格式
                required_columns = [
                    '期号', '前区7个热门数字', '后一期中奖数字前区数字',
                    '后区热门4个数字', '后一期中奖数字后区数字',
                    '前区7个冷门数字', '后区冷门4个数字'
                ]
                
                if not all(col in df.columns for col in required_columns):
                    flash('Excel文件格式不正确，请确保包含所有必需的列')
                    return redirect(request.url)
                
                # 导入数据
                for _, row in df.iterrows():
                    existing = ManualImportData.query.filter_by(draw_number=row['期号']).first()
                    if not existing:
                        new_data = ManualImportData(
                            draw_number=row['期号'],
                            front_hot_numbers=row['前区7个热门数字'],
                            next_front_numbers=row['后一期中奖数字前区数字'],
                            back_hot_numbers=row['后区热门4个数字'],
                            next_back_numbers=row['后一期中奖数字后区数字'],
                            front_cold_numbers=row['前区7个冷门数字'],
                            back_cold_numbers=row['后区冷门4个数字']
                        )
                        db.session.add(new_data)
                
                db.session.commit()
                flash('数据导入成功')
                
            except Exception as e:
                flash(f'导入失败：{str(e)}')
                db.session.rollback()
        
        else:
            flash('请上传Excel文件（.xlsx格式）')
    
    # 获取所有导入的数据
    data = ManualImportData.query.order_by(ManualImportData.draw_number.desc()).all()
    return render_template('manual_data.html', data=data)

@main.route('/export-manual-data')
@login_required
def export_manual_data():
    # 获取所有数据
    data = ManualImportData.query.order_by(ManualImportData.draw_number.desc()).all()
    
    # 创建DataFrame
    df = pd.DataFrame([{
        '期号': item.draw_number,
        '前区7个热门数字': item.front_hot_numbers,
        '后一期中奖数字前区数字': item.next_front_numbers,
        '后区热门4个数字': item.back_hot_numbers,
        '后一期中奖数字后区数字': item.next_back_numbers,
        '前区7个冷门数字': item.front_cold_numbers,
        '后区冷门4个数字': item.back_cold_numbers
    } for item in data])
    
    # 创建Excel文件
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='数据')
    
    output.seek(0)
    
    # 生成文件名
    filename = f'manual_data_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )

@main.route('/insert-historical-data')
@login_required
def insert_historical_data():
    try:
        # 获取最近100期开奖数据
        draws = LotteryDraw.query.order_by(LotteryDraw.draw_date.desc()).limit(100).all()
        
        # 按时间顺序处理
        draws = sorted(draws, key=lambda x: x.draw_date)
        
        for i in range(len(draws)-1):  # 遍历到倒数第二期，因为需要下一期的数据
            current_draw = draws[i]
            next_draw = draws[i+1]
            
            # 获取当前期的热门和冷门号码
            # 获取前100期数据用于计算热门冷门
            analysis_draws = LotteryDraw.query.order_by(LotteryDraw.draw_date.desc()).limit(100).all()
            
            # 初始化频率统计
            front_freq = defaultdict(int)
            back_freq = defaultdict(int)
            
            # 记录每个号码最后出现的期数
            front_last_appear = defaultdict(int)
            back_last_appear = defaultdict(int)
            
            for idx, draw in enumerate(analysis_draws):
                front_nums = draw.numbers.split('+')[0].split(',')
                back_nums = draw.numbers.split('+')[1].split(',')
                
                for num in front_nums:
                    front_freq[num] += 1
                    if front_last_appear[num] == 0:
                        front_last_appear[num] = idx
                        
                for num in back_nums:
                    back_freq[num] += 1
                    if back_last_appear[num] == 0:
                        back_last_appear[num] = idx
            
            # 获取热门号码
            front_hot_numbers = sorted(front_freq.items(), key=lambda x: x[1], reverse=True)[:7]
            back_hot_numbers = sorted(back_freq.items(), key=lambda x: x[1], reverse=True)[:4]
            
            # 获取冷门号码
            front_cold_numbers = []
            back_cold_numbers = []
            
            for num in [f"{i:02d}" for i in range(1, 36)]:
                if num not in front_freq:
                    front_cold_numbers.append((num, 100))
                else:
                    front_cold_numbers.append((num, front_last_appear[num]))
                    
            for num in [f"{i:02d}" for i in range(1, 13)]:
                if num not in back_freq:
                    back_cold_numbers.append((num, 100))
                else:
                    back_cold_numbers.append((num, back_last_appear[num]))
            
            front_cold_numbers.sort(key=lambda x: x[1], reverse=True)
            back_cold_numbers.sort(key=lambda x: x[1], reverse=True)
            
            front_cold_numbers = front_cold_numbers[:7]
            back_cold_numbers = back_cold_numbers[:4]
            
            # 创建新记录
            new_data = ManualImportData(
                draw_number=current_draw.draw_number,
                front_hot_numbers=','.join([num for num, _ in front_hot_numbers]),
                next_front_numbers=next_draw.numbers.split('+')[0],
                back_hot_numbers=','.join([num for num, _ in back_hot_numbers]),
                next_back_numbers=next_draw.numbers.split('+')[1],
                front_cold_numbers=','.join([num for num, _ in front_cold_numbers]),
                back_cold_numbers=','.join([num for num, _ in back_cold_numbers])
            )
            
            # 检查是否已存在
            existing = ManualImportData.query.filter_by(draw_number=current_draw.draw_number).first()
            if not existing:
                db.session.add(new_data)
        
        db.session.commit()
        flash('历史数据导入成功')
        
    except Exception as e:
        flash(f'导入失败：{str(e)}')
        db.session.rollback()
    
    return redirect(url_for('main.manual_data')) 