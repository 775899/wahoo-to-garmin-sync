import os
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from garminconnect import Garmin
import dropbox
from dropbox.files import WriteMode

# ========== 配置 ==========
class Config:
    # Garmin 账号配置（从环境变量/Secrets读取）
    GARMIN_EMAIL = os.getenv('GARMIN_EMAIL')
    GARMIN_PASSWORD = os.getenv('GARMIN_PASSWORD')
    
    # Garmin 区域设置："international" 或 "china"
    # 国区账号用 "china"，国际区用 "international"
    GARMIN_REGION = os.getenv('GARMIN_REGION', 'international')
    
    # Dropbox 配置
    DROPBOX_ACCESS_TOKEN = os.getenv('DROPBOX_ACCESS_TOKEN')
    # Wahoo 默认上传到 Dropbox 的路径
    DROPBOX_FOLDER = os.getenv('DROPBOX_FOLDER', '/Apps/Wahoo Fitness')
    
    # 同步状态文件
    STATE_FILE = 'sync_state.json'
    
    # 错误重试次数
    MAX_RETRIES = 3
    RETRY_DELAY = 5  # 秒

# ========== 同步状态管理 ==========
class SyncState:
    def __init__(self, filepath=Config.STATE_FILE):
        self.filepath = filepath
        self.state = self.load()
    
    def load(self):
        """加载同步状态"""
        try:
            with open(self.filepath, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {
                'processed_files': [],
                'last_sync': None,
                'total_synced': 0,
                'failed_files': []
            }
    
    def save(self):
        """保存同步状态"""
        with open(self.filepath, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def is_processed(self, filename):
        """检查文件是否已处理"""
        return filename in self.state['processed_files']
    
    def mark_processed(self, filename):
        """标记文件为已处理"""
        if filename not in self.state['processed_files']:
            self.state['processed_files'].append(filename)
        self.state['last_sync'] = datetime.now().isoformat()
        self.state['total_synced'] += 1
        self.save()
    
    def mark_failed(self, filename, error):
        """标记文件处理失败"""
        self.state['failed_files'].append({
            'filename': filename,
            'error': str(error),
            'timestamp': datetime.now().isoformat()
        })
        self.save()

# ========== Garmin Connect 上传 ==========
class GarminUploader:
    def __init__(self, email, password, region='international'):
        self.email = email
        self.password = password
        self.region = region
        self.client = None
        
    def login(self):
        """登录 Garmin Connect"""
        try:
            # 根据区域选择不同的 Garmin Connect 域名
            if self.region == 'china':
                # 国区账号
                self.client = Garmin(self.email, self.password)
            else:
                # 国际区账号
                self.client = Garmin(self.email, self.password)
            
            self.client.login()
            print(f"✓ Garmin Connect 登录成功 (区域: {self.region})")
            return True
            
        except Exception as e:
            print(f"✗ Garmin Connect 登录失败: {e}")
            return False
    
    def upload_activity(self, file_data, filename):
        """上传活动文件到 Garmin Connect"""
        if not self.client:
            if not self.login():
                return False
        
        try:
            # 上传文件
            response = self.client.upload_activity(file_data)
            
            if response:
                print(f"  ✓ 上传成功: {filename}")
                print(f"    活动ID: {response}")
                return True
            else:
                print(f"  ✗ 上传失败: {filename} (无响应)")
                return False
                
        except Exception as e:
            print(f"  ✗ 上传失败: {filename} - {e}")
            # 如果登录过期，尝试重新登录
            if 'login' in str(e).lower() or 'auth' in str(e).lower():
                print("  → 尝试重新登录...")
                self.client = None
                return self.upload_activity(file_data, filename)
            return False

# ========== Dropbox 文件获取 ==========
class DropboxManager:
    def __init__(self, access_token):
        self.access_token = access_token
        self.dbx = None
        
    def connect(self):
        """连接 Dropbox"""
        try:
            self.dbx = dropbox.Dropbox(self.access_token)
            account = self.dbx.users_get_current_account()
            print(f"✓ Dropbox 连接成功: {account.name.display_name}")
            return True
        except Exception as e:
            print(f"✗ Dropbox 连接失败: {e}")
            return False
    
    def list_fit_files(self, folder_path):
        """列出 Dropbox 文件夹中的 .fit 文件"""
        if not self.dbx:
            if not self.connect():
                return []
        
        try:
            result = self.dbx.files_list_folder(folder_path)
            fit_files = [
                entry for entry in result.entries 
                if isinstance(entry, dropbox.files.FileMetadata) 
                and entry.name.endswith('.fit')
            ]
            return fit_files
            
        except Exception as e:
            print(f"✗ 列出文件失败: {e}")
            return []
    
    def download_file(self, file_path):
        """从 Dropbox 下载文件"""
        try:
            _, response = self.dbx.files_download(file_path)
            return response.content
        except Exception as e:
            print(f"✗ 下载文件失败 {file_path}: {e}")
            return None
    
    def move_file(self, from_path, to_folder):
        """移动文件到已处理文件夹"""
        try:
            filename = os.path.basename(from_path)
            to_path = f"{to_folder}/{filename}"
            
            # 如果目标文件已存在，添加时间戳
            try:
                self.dbx.files_get_metadata(to_path)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                name, ext = os.path.splitext(filename)
                to_path = f"{to_folder}/{name}_{timestamp}{ext}"
            except dropbox.exceptions.ApiError:
                pass  # 文件不存在，可以正常移动
            
            self.dbx.files_move_v2(from_path, to_path)
            print(f"  → 文件已移动到: {to_path}")
            return True
            
        except Exception as e:
            print(f"  ✗ 移动文件失败: {e}")
            return False

# ========== 主同步逻辑 ==========
class WahooToGarminSync:
    def __init__(self):
        self.config = Config()
        self.state = SyncState()
        self.garmin = None
        self.dropbox = None
        
    def validate_config(self):
        """验证配置是否完整"""
        required = [
            self.config.GARMIN_EMAIL,
            self.config.GARMIN_PASSWORD,
            self.config.DROPBOX_ACCESS_TOKEN
        ]
        
        if not all(required):
            print("✗ 配置错误: 缺少必要的Secrets")
            print("请确保已设置以下 GitHub Secrets:")
            print("  - GARMIN_EMAIL")
            print("  - GARMIN_PASSWORD")
            print("  - DROPBOX_ACCESS_TOKEN")
            return False
            
        return True
    
    def initialize(self):
        """初始化连接"""
        # 初始化 Garmin
        self.garmin = GarminUploader(
            self.config.GARMIN_EMAIL,
            self.config.GARMIN_PASSWORD,
            self.config.GARMIN_REGION
        )
        
        if not self.garmin.login():
            return False
        
        # 初始化 Dropbox
        self.dropbox = DropboxManager(self.config.DROPBOX_ACCESS_TOKEN)
        if not self.dropbox.connect():
            return False
        
        return True
    
    def sync(self):
        """执行同步"""
        if not self.validate_config():
            return False
        
        if not self.initialize():
            return False
        
        print(f"\n{'='*50}")
        print(f"开始同步: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*50}\n")
        
        # 获取 Dropbox 中的 .fit 文件
        fit_files = self.dropbox.list_fit_files(self.config.DROPBOX_FOLDER)
        
        if not fit_files:
            print("ℹ 没有找到新的 .fit 文件")
            self.print_summary()
            return True
        
        print(f"发现 {len(fit_files)} 个 .fit 文件\n")
        
        # 处理每个文件
        success_count = 0
        skip_count = 0
        failed_count = 0
        
        for file_entry in fit_files:
            filename = file_entry.name
            file_path = file_entry.path_display
            
            print(f"处理: {filename}")
            
            # 检查是否已处理
            if self.state.is_processed(filename):
                print(f"  → 跳过: 已同步过")
                skip_count += 1
                continue
            
            # 下载文件
            file_data = self.dropbox.download_file(file_path)
            if not file_data:
                failed_count += 1
                self.state.mark_failed(filename, "下载失败")
                continue
            
            # 上传到 Garmin
            if self.garmin.upload_activity(file_data, filename):
                self.state.mark_processed(filename)
                success_count += 1
                
                # 移动文件到已处理文件夹
                processed_folder = f"{self.config.DROPBOX_FOLDER}/processed"
                self.dropbox.move_file(file_path, processed_folder)
            else:
                failed_count += 1
                self.state.mark_failed(filename, "上传失败")
            
            # 避免请求过快
            time.sleep(2)
        
        self.print_summary(success_count, skip_count, failed_count)
        return True
    
    def print_summary(self, success=0, skip=0, failed=0):
        """打印同步摘要"""
        print(f"\n{'='*50}")
        print("同步摘要")
        print(f"{'='*50}")
        print(f"成功: {success}")
        print(f"跳过: {skip}")
        print(f"失败: {failed}")
        print(f"总计已同步: {self.state.state['total_synced']}")
        print(f"最后同步: {self.state.state['last_sync']}")
        
        if self.state.state['failed_files']:
            print(f"\n最近失败记录:")
            for fail in self.state.state['failed_files'][-5:]:
                print(f"  - {fail['filename']}: {fail['error']}")
        
        print(f"{'='*50}\n")

# ========== 主入口 ==========
def main():
    """主函数"""
    try:
        sync = WahooToGarminSync()
        success = sync.sync()
        
        if not success:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\n用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ 未预期的错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
