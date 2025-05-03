import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime
import time
from app.models import LotteryDraw
from app import db
import logging
import random
from collections import Counter, defaultdict
import numpy as np
from itertools import combinations
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
import pandas as pd

# 配置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class LotterySpider:
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
            'Accept': 'application/json',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': 'https://www.lottery.gov.cn/',
            'Origin': 'https://www.lottery.gov.cn',
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive'
        }
        # 更新为新的API地址
        self.base_url = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
    
    def parse_lottery_numbers(self, result_str):
        """解析开奖号码字符串
        
        Args:
            result_str: 开奖号码字符串，可能的格式：
                - "01 02 03 04 05 06 07" (空格分隔)
                - "01,02,03,04,05|06,07" (逗号和竖线分隔)
                
        Returns:
            tuple: (front_numbers, back_numbers) 格式化后的号码列表
        """
        try:
            # 首先尝试用竖线分隔
            if '|' in result_str:
                front_part, back_part = result_str.split('|')
                front_numbers = [num.strip().zfill(2) for num in front_part.split(',') if num.strip()]
                back_numbers = [num.strip().zfill(2) for num in back_part.split(',') if num.strip()]
            else:
                # 如果没有竖线，假设是空格分隔，前5个是前区号码，后2个是后区号码
                numbers = [num.strip().zfill(2) for num in result_str.split() if num.strip()]
                if len(numbers) != 7:
                    raise ValueError(f"Invalid number count: {len(numbers)}, expected 7")
                front_numbers = numbers[:5]
                back_numbers = numbers[5:]
            
            # 验证号码个数
            if len(front_numbers) != 5 or len(back_numbers) != 2:
                raise ValueError(f"Invalid number count: front={len(front_numbers)}, back={len(back_numbers)}")
            
            # 验证号码范围
            for num in front_numbers:
                if not (1 <= int(num) <= 35):
                    raise ValueError(f"Invalid front number: {num}")
            for num in back_numbers:
                if not (1 <= int(num) <= 12):
                    raise ValueError(f"Invalid back number: {num}")
            
            return front_numbers, back_numbers
            
        except Exception as e:
            logger.error(f"Error parsing lottery numbers '{result_str}': {str(e)}")
            raise
        
    def parse_prize_info(self, prize_list):
        """解析奖金信息
        
        Args:
            prize_list: API返回的奖项列表
            
        Returns:
            tuple: (first_prize_num, first_prize_amount) 一等奖注数和单注奖金
        """
        try:
            # 找到基本一等奖信息
            first_prize_info = next((prize for prize in prize_list 
                                   if prize.get('prizeLevel') == '一等奖' 
                                   and prize.get('awardType') == 0), None)
            
            if not first_prize_info:
                return 0, 0.0
            
            # 解析注数和奖金
            stake_count_str = first_prize_info.get('stakeCount', '0')
            stake_amount_str = first_prize_info.get('stakeAmount', '0')
            
            # 处理特殊值
            if stake_count_str == '---' or stake_count_str == '--':
                stake_count = 0
            else:
                stake_count = int(stake_count_str)
                
            if stake_amount_str == '---' or stake_amount_str == '--':
                stake_amount = 0.0
            else:
                stake_amount = float(stake_amount_str.replace(',', ''))
            
            return stake_count, stake_amount
            
        except Exception as e:
            logger.error(f"Error parsing prize information: {str(e)}")
            return 0, 0.0
    
    def fetch_latest_draw(self):
        """获取最新一期开奖数据"""
        try:
            params = {
                'gameNo': '85',  # 大乐透的游戏编号
                'provinceId': '0',
                'pageSize': '1',
                'isVerify': '1',
                'pageNo': '1'
            }
            
            response = requests.get(
                self.base_url,
                params=params,
                headers=self.headers,
                timeout=10
            )
            
            logger.info(f"API Response Status: {response.status_code}")
            
            if response.status_code != 200:
                logger.error(f"Request failed with status code: {response.status_code}")
                logger.error(f"Response content: {response.text[:500]}")
                return None
                
            data = response.json()
            if not data or 'value' not in data or not data['value'].get('lastPoolDraw'):
                logger.error("No data found in response")
                logger.error(f"Response content: {response.text[:500]}")
                return None
                
            latest = data['value']['lastPoolDraw']
            
            try:
                # 解析开奖号码
                front_numbers, back_numbers = self.parse_lottery_numbers(latest['lotteryDrawResult'])
                numbers_str = ','.join(front_numbers) + '+' + ','.join(back_numbers)
            except Exception as e:
                logger.error(f"Failed to parse lottery numbers: {str(e)}")
                return None
            
            try:
                # 解析日期
                draw_date = datetime.strptime(latest['lotteryDrawTime'], '%Y-%m-%d').date()
            except Exception as e:
                logger.error(f"Failed to parse draw date: {str(e)}")
                return None
            
            try:
                # 解析奖金信息
                prize_list = latest.get('prizeLevelList', [])
                first_prize_num, first_prize_amount = self.parse_prize_info(prize_list)
                
                # 处理奖池金额中的逗号
                pool_balance = latest.get('poolBalanceAfterdraw', '0').replace(',', '')
                
                return {
                    'draw_number': latest['lotteryDrawNum'],
                    'draw_date': draw_date,
                    'numbers': numbers_str,
                    'prize_pool': float(pool_balance),
                    'first_prize_num': first_prize_num,
                    'first_prize_amount': first_prize_amount
                }
            except Exception as e:
                logger.error(f"Failed to parse prize information: {str(e)}")
                return None
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Network error: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error fetching lottery data: {str(e)}")
            return None
    
    def update_database(self):
        """更新数据库中的开奖数据"""
        try:
            latest_data = self.fetch_latest_draw()
            if not latest_data:
                return False, "无法获取最新开奖数据，请稍后重试"
            
            # 检查是否已存在
            existing_draw = LotteryDraw.query.filter_by(draw_number=latest_data['draw_number']).first()
            if existing_draw:
                return False, "该期数据已存在"
            
            # 创建新记录
            new_draw = LotteryDraw(**latest_data)
            db.session.add(new_draw)
            
            # 更新用户预测的中奖状态
            from app.models import UserPrediction
            predictions = UserPrediction.query.filter_by(
                draw_number=None,
                is_hit=False,
                prize_amount=0
            ).all()
            
            for prediction in predictions:
                # 检查是否中奖
                pred_numbers = set(prediction.numbers.replace('+', ',').split(','))
                draw_numbers = set(latest_data['numbers'].replace('+', ',').split(','))
                
                if pred_numbers == draw_numbers:
                    prediction.is_hit = True
                    prediction.prize_amount = latest_data['first_prize_amount']
                prediction.draw_number = latest_data['draw_number']
            
            db.session.commit()
            return True, "数据更新成功"
            
        except Exception as e:
            logger.error(f"Error updating database: {str(e)}")
            db.session.rollback()
            return False, f"更新数据失败：{str(e)}"
            
    def fetch_historical_data(self, pages=5):
        """获取历史开奖数据"""
        all_data = []
        try:
            params = {
                'gameNo': '85',
                'provinceId': '0',
                'pageSize': str(pages * 30),
                'isVerify': '1',
                'pageNo': '1'
            }
            
            response = requests.get(
                self.base_url,
                params=params,
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code != 200:
                logger.error(f"Request failed with status code: {response.status_code}")
                return all_data
                
            data = response.json()
            if not data or 'value' not in data or 'list' not in data['value']:
                logger.error("Invalid response format")
                return all_data
                
            for draw in data['value']['list']:
                try:
                    # 解析开奖号码
                    front_numbers, back_numbers = self.parse_lottery_numbers(draw['lotteryDrawResult'])
                    numbers_str = ','.join(front_numbers) + '+' + ','.join(back_numbers)
                    
                    # 解析日期
                    draw_date = datetime.strptime(draw['lotteryDrawTime'], '%Y-%m-%d').date()
                    
                    # 解析奖金信息
                    prize_list = draw.get('prizeLevelList', [])
                    first_prize_num, first_prize_amount = self.parse_prize_info(prize_list)
                    
                    # 处理奖池金额中的逗号
                    pool_balance = draw.get('poolBalanceAfterdraw', '0').replace(',', '')
                    
                    all_data.append({
                        'draw_number': draw['lotteryDrawNum'],
                        'draw_date': draw_date,
                        'numbers': numbers_str,
                        'prize_pool': float(pool_balance),
                        'first_prize_num': first_prize_num,
                        'first_prize_amount': first_prize_amount
                    })
                    
                except Exception as e:
                    logger.error(f"Error parsing draw data for {draw.get('lotteryDrawNum', 'unknown')}: {str(e)}")
                    continue
                    
            return all_data
            
        except Exception as e:
            logger.error(f"Error fetching historical data: {str(e)}")
            return all_data
    
    def _extract_features(self, draws):
        """从历史数据中提取特征
        
        Args:
            draws: 历史开奖记录列表
            
        Returns:
            tuple: (X, y_front, y_back) 特征矩阵和标签
        """
        features = []
        front_targets = []
        back_targets = []
        
        # 使用最近10期的数据作为特征
        window_size = 10
        
        for i in range(window_size, len(draws)):
            # 获取当前期的号码
            current_draw = draws[i]
            current_front = set(current_draw.numbers.split('+')[0].split(','))
            current_back = set(current_draw.numbers.split('+')[1].split(','))
            
            # 特征列表
            draw_features = []
            
            # 1. 前区号码频率统计
            front_freq = defaultdict(int)
            for j in range(i - window_size, i):
                front_nums = set(draws[j].numbers.split('+')[0].split(','))
                for num in front_nums:
                    front_freq[num] += 1
            
            # 2. 后区号码频率统计
            back_freq = defaultdict(int)
            for j in range(i - window_size, i):
                back_nums = set(draws[j].numbers.split('+')[1].split(','))
                for num in back_nums:
                    back_freq[num] += 1
            
            # 3. 计算距离上次出现的期数
            front_last_appear = defaultdict(lambda: window_size)
            back_last_appear = defaultdict(lambda: window_size)
            for j in range(i - 1, i - window_size - 1, -1):
                front_nums = set(draws[j].numbers.split('+')[0].split(','))
                back_nums = set(draws[j].numbers.split('+')[1].split(','))
                for num in front_nums:
                    if front_last_appear[num] == window_size:
                        front_last_appear[num] = i - j
                for num in back_nums:
                    if back_last_appear[num] == window_size:
                        back_last_appear[num] = i - j
            
            # 4. 计算号码的平均间隔
            front_intervals = []
            back_intervals = []
            for j in range(i - window_size, i):
                if j > 0:
                    prev_front = set(draws[j-1].numbers.split('+')[0].split(','))
                    curr_front = set(draws[j].numbers.split('+')[0].split(','))
                    front_intervals.append(len(prev_front & curr_front))
                    
                    prev_back = set(draws[j-1].numbers.split('+')[1].split(','))
                    curr_back = set(draws[j].numbers.split('+')[1].split(','))
                    back_intervals.append(len(prev_back & curr_back))
            
            # 添加特征
            # 前区频率特征
            for i in range(1, 36):
                num = f"{i:02d}"
                draw_features.append(front_freq[num])
            # 后区频率特征
            for i in range(1, 13):
                num = f"{i:02d}"
                draw_features.append(back_freq[num])
            # 前区上次出现间隔特征
            for i in range(1, 36):
                num = f"{i:02d}"
                draw_features.append(front_last_appear[num])
            # 后区上次出现间隔特征
            for i in range(1, 13):
                num = f"{i:02d}"
                draw_features.append(back_last_appear[num])
            # 号码重复特征
            draw_features.append(np.mean(front_intervals))
            draw_features.append(np.mean(back_intervals))
            
            features.append(draw_features)
            front_targets.append([1 if f"{i:02d}" in current_front else 0 for i in range(1, 36)])
            back_targets.append([1 if f"{i:02d}" in current_back else 0 for i in range(1, 13)])
        
        return np.array(features), np.array(front_targets), np.array(back_targets)

    def train_ml_model(self):
        """训练机器学习模型"""
        try:
            # 获取历史数据
            draws = LotteryDraw.query.order_by(LotteryDraw.draw_date.asc()).all()
            if len(draws) < 50:  # 确保有足够的训练数据
                return None, None
            
            # 提取特征和标签
            X, y_front, y_back = self._extract_features(draws)
            
            # 划分训练集和测试集
            X_train, X_test, y_front_train, y_front_test, y_back_train, y_back_test = train_test_split(
                X, y_front, y_back, test_size=0.2, random_state=42
            )
            
            # 标准化特征
            scaler = StandardScaler()
            X_train_scaled = scaler.fit_transform(X_train)
            X_test_scaled = scaler.transform(X_test)
            
            # 训练前区模型
            front_model = RandomForestClassifier(n_estimators=100, random_state=42)
            front_model.fit(X_train_scaled, y_front_train)
            
            # 训练后区模型
            back_model = RandomForestClassifier(n_estimators=100, random_state=42)
            back_model.fit(X_train_scaled, y_back_train)
            
            return front_model, back_model, scaler
            
        except Exception as e:
            logger.error(f"Error training ML models: {str(e)}")
            return None, None, None

    def predict_with_ml(self, num_suggestions=3):
        """使用机器学习模型生成预测号码"""
        try:
            # 训练模型
            front_model, back_model, scaler = self.train_ml_model()
            if not all([front_model, back_model, scaler]):
                return []
            
            # 获取最近数据作为预测特征
            draws = LotteryDraw.query.order_by(LotteryDraw.draw_date.desc()).limit(10).all()
            if len(draws) < 10:
                return []
            
            # 准备预测特征
            X_pred = self._extract_features(list(reversed(draws)) + [draws[0]])[0][-1:]
            X_pred_scaled = scaler.transform(X_pred)
            
            # 预测概率
            front_probs = front_model.predict_proba(X_pred_scaled)[0]
            back_probs = back_model.predict_proba(X_pred_scaled)[0]
            
            suggestions = []
            for _ in range(num_suggestions):
                # 根据概率选择号码
                selected_front = []
                front_numbers = [f"{i:02d}" for i in range(1, 36)]
                while len(selected_front) < 5:
                    weights = [front_probs[i][1] for i in range(35)]
                    num = np.random.choice(front_numbers, p=weights/np.sum(weights))
                    if num not in selected_front:
                        selected_front.append(num)
                
                selected_back = []
                back_numbers = [f"{i:02d}" for i in range(1, 13)]
                while len(selected_back) < 2:
                    weights = [back_probs[i][1] for i in range(12)]
                    num = np.random.choice(back_numbers, p=weights/np.sum(weights))
                    if num not in selected_back:
                        selected_back.append(num)
                
                # 排序号码
                selected_front.sort(key=lambda x: int(x))
                selected_back.sort(key=lambda x: int(x))
                
                # 组合号码
                numbers = ','.join(selected_front) + '+' + ','.join(selected_back)
                suggestions.append({
                    'numbers': numbers,
                    'strategy_name': 'ml',
                    'reason': "基于机器学习模型预测的号码组合"
                })
            
            return suggestions
            
        except Exception as e:
            logger.error(f"Error generating ML predictions: {str(e)}")
            return []

    def recommend_numbers(self, strategy='smart', num_suggestions=5):
        """生成号码推荐
        
        Args:
            strategy: 选号策略，可选值：
                - 'smart': 智能选号（综合策略）
                - 'hot': 热门号码优先
                - 'cold': 冷门号码优先
                - 'balanced': 平衡选号
                - 'random': 随机选号
                - 'ml': 机器学习预测
            num_suggestions: 推荐组数
            
        Returns:
            list: 推荐号码列表，每个元素为一个字典，包含：
                - numbers: 推荐号码字符串
                - strategy_name: 使用的策略名称
                - reason: 推荐理由
        """
        try:
            if strategy == 'ml':
                return self.predict_with_ml(num_suggestions)
            
            # 获取最近100期开奖数据
            draws = LotteryDraw.query.order_by(LotteryDraw.draw_date.desc()).limit(100).all()
            if not draws:
                return []
            
            # 分析号码频率
            front_freq = defaultdict(int)
            back_freq = defaultdict(int)
            front_last_appear = defaultdict(int)
            back_last_appear = defaultdict(int)
            
            for idx, draw in enumerate(draws):
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
            
            # 计算平均频率
            front_avg_freq = sum(front_freq.values()) / len(front_freq) if front_freq else 0
            back_avg_freq = sum(back_freq.values()) / len(back_freq) if back_freq else 0
            
            suggestions = []
            
            if strategy == 'smart':
                # 使用多种策略生成推荐
                strategies = ['hot', 'balanced', 'cold']
                weights = [0.4, 0.4, 0.2]  # 权重分配
                counts = np.random.multinomial(num_suggestions, weights)
                
                for strat, count in zip(strategies, counts):
                    suggestions.extend(self._generate_numbers(
                        strat, count, front_freq, back_freq,
                        front_last_appear, back_last_appear,
                        front_avg_freq, back_avg_freq
                    ))
            else:
                # 使用单一策略
                suggestions = self._generate_numbers(
                    strategy, num_suggestions, front_freq, back_freq,
                    front_last_appear, back_last_appear,
                    front_avg_freq, back_avg_freq
                )
            
            # 确保不重复
            seen = set()
            unique_suggestions = []
            for sugg in suggestions:
                if sugg['numbers'] not in seen:
                    seen.add(sugg['numbers'])
                    unique_suggestions.append(sugg)
            
            return unique_suggestions[:num_suggestions]
            
        except Exception as e:
            logger.error(f"Error generating number recommendations: {str(e)}")
            return []
    
    def _weighted_sample(self, population, weights, k, strategy='hot'):
        """加权随机采样
        
        Args:
            population: 待采样的总体
            weights: 权重列表
            k: 采样数量
            strategy: 采样策略，默认为'hot'
            
        Returns:
            list: 采样结果
        """
        weights = np.array(weights)
        if strategy == 'cold':
            # 对于冷门号码，权重需要反转
            weights = np.max(weights) - weights
        weights = weights / weights.sum()  # 归一化
        return random.choices(population, weights=weights, k=k)

    def _generate_numbers(self, strategy, count, front_freq, back_freq,
                         front_last_appear, back_last_appear,
                         front_avg_freq, back_avg_freq):
        """根据特定策略生成号码"""
        suggestions = []
        front_numbers = [f"{i:02d}" for i in range(1, 36)]
        back_numbers = [f"{i:02d}" for i in range(1, 13)]
        
        for _ in range(count):
            if strategy == 'hot':
                # 选择频率较高的号码
                front_probs = [front_freq.get(n, 0) for n in front_numbers]
                back_probs = [back_freq.get(n, 0) for n in back_numbers]
                
                # 使用集合确保不重复
                selected_front = []
                while len(selected_front) < 5:
                    num = self._weighted_sample(front_numbers, front_probs, 1, 'hot')[0]
                    if num not in selected_front:
                        selected_front.append(num)
                
                selected_back = []
                while len(selected_back) < 2:
                    num = self._weighted_sample(back_numbers, back_probs, 1, 'hot')[0]
                    if num not in selected_back:
                        selected_back.append(num)
                
                reason = "基于近期热门号码分布"
                
            elif strategy == 'cold':
                # 选择最近未出现的号码
                front_probs = [front_last_appear.get(n, 100) for n in front_numbers]
                back_probs = [back_last_appear.get(n, 100) for n in back_numbers]
                
                # 使用集合确保不重复
                selected_front = []
                while len(selected_front) < 5:
                    num = self._weighted_sample(front_numbers, front_probs, 1, 'cold')[0]
                    if num not in selected_front:
                        selected_front.append(num)
                
                selected_back = []
                while len(selected_back) < 2:
                    num = self._weighted_sample(back_numbers, back_probs, 1, 'cold')[0]
                    if num not in selected_back:
                        selected_back.append(num)
                
                reason = "选择近期未出现的冷门号码"
                
            elif strategy == 'balanced':
                # 混合选择热门和冷门号码
                hot_front = [n for n, f in front_freq.items() if f > front_avg_freq]
                cold_front = [n for n, f in front_freq.items() if f <= front_avg_freq]
                hot_back = [n for n, f in back_freq.items() if f > back_avg_freq]
                cold_back = [n for n, f in back_freq.items() if f <= back_avg_freq]
                
                if len(hot_front) < 3:
                    hot_count = len(hot_front)
                    cold_count = 5 - hot_count
                else:
                    hot_count = 3
                    cold_count = 2
                
                # 使用集合确保不重复
                selected_front = []
                # 先选热门号码
                hot_front_copy = hot_front.copy()
                while len(selected_front) < hot_count and hot_front_copy:
                    num = random.choice(hot_front_copy)
                    hot_front_copy.remove(num)
                    selected_front.append(num)
                
                # 再选冷门号码
                cold_front_copy = [n for n in cold_front if n not in selected_front]
                while len(selected_front) < 5 and cold_front_copy:
                    num = random.choice(cold_front_copy)
                    cold_front_copy.remove(num)
                    selected_front.append(num)
                
                # 如果还不够，从剩余号码中随机选择
                if len(selected_front) < 5:
                    remaining = list(set(front_numbers) - set(selected_front))
                    selected_front.extend(random.sample(remaining, 5 - len(selected_front)))
                
                # 后区号码选择
                selected_back = []
                # 选择一个热门号码
                if hot_back:
                    selected_back.append(random.choice(hot_back))
                # 选择一个冷门号码
                remaining_back = [n for n in back_numbers if n not in selected_back]
                selected_back.append(random.choice(remaining_back))
                
                reason = "平衡选择热门号码和冷门号码"
                
            else:  # random strategy
                selected_front = random.sample(front_numbers, 5)
                selected_back = random.sample(back_numbers, 2)
                reason = "完全随机选择"
            
            # 对号码排序
            selected_front.sort(key=lambda x: int(x))
            selected_back.sort(key=lambda x: int(x))
            
            # 组合号码
            numbers = ','.join(selected_front) + '+' + ','.join(selected_back)
            suggestions.append({
                'numbers': numbers,
                'strategy_name': strategy,
                'reason': reason
            })
        
        return suggestions 