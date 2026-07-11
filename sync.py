import os
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta
from garminconnect import Garmin
import dropbox
from dropbox.files import WriteMode

SUPPORTED_FORMATS = ('.fit', '.gpx', '.tcx')

class Config:
    GARMIN_EMAIL = os.getenv('GARMIN_EMAIL')
    GARMIN_PASSWORD = os.getenv('GARMIN_PASSWORD')
    GARMIN_REGION = os.getenv('GARMIN_REGION', 'international')
    
    DROPBOX_REFRESH_TOKEN = os.getenv('DROPBOX_REFRESH_TOKEN')
    DROPBOX_APP_KEY = os.getenv('DROPBOX_APP_KEY')
    DROPBOX_APP_SECRET = os.getenv('DROPBOX_APP_SECRET')
    DROPBOX_ACCESS_TOKEN = os.getenv('DROPBOX_ACCESS_TOKEN')
    
    DROPBOX_FOLDER = os.getenv('DROPBOX_FOLDER', '/Apps/Wahoo Fitness')
    RECURSIVE_SEARCH = os.getenv('RECURSIVE_SEARCH', 'true').lower() == 'true'
    STATE_FILE = 'sync_state.json'
    MAX_RETRIES = 3
    RETRY_DELAY = 5

class SyncState:
    def __init__(self, filepath=Config.STATE_FILE):
        self.filepath = filepath
        self.state = self.load()
    
    def load(self):
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
        with open(self.filepath, 'w') as f:
            json.dump(self.state, f, indent=2)
    
    def is_processed(self, filename):
        return filename in self.state['processed_files']
    
    def mark_processed(self, filename):
        if filename not in self.state['processed_files']:
            self.state['processed_files'].append(filename)
        self.state['last_sync'] = datetime.now().isoformat()
        self.state['total_synced'] += 1
        self.save()
    
    def mark_failed(self, filename, error):
        self.state['failed_files'].append({
            'filename': filename,
            'error': str(error),
            'timestamp': datetime.now().isoformat()
        })
        self.save()

class GarminUploader:
    def __init__(self, email, password, region='international'):
        self.email = email
        self.password = password
        self.region = region
        self.client = None
        
    def login(self):
        try:
            # 通过 is_cn 参数让 garminconnect 库在构造时选择正确的域名
            # garminconnect 源码: domain="garmin.cn" if is_cn else "garmin.com"
            # 注意: 必须在创建客户端时传入，创建后再设环境变量无效
            is_cn = (self.region == 'china')
            self.client = Garmin(self.email, self.password, is_cn=is_cn)

            if is_cn:
                print(f"Garmin region set to: china (garmin.cn)")
            else:
                print(f"Garmin region set to: international (garmin.com)")

            self.client.login()
            print(f"Garmin Connect login successful")
            return True
        except Exception as e:
            print(f"Garmin Connect login failed: {e}")
            return False
    
    def upload_activity(self, file_data, filename):
        """Upload activity to Garmin Connect (save bytes to temp file first)"""
        if not self.client:
            if not self.login():
                return False
        
        import tempfile
        temp_path = None
        try:
            suffix = os.path.splitext(filename)[1] or '.fit'
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                tmp.write(file_data)
                temp_path = tmp.name
            
            response = self.client.upload_activity(temp_path)
            
            if response:
                print(f"  Upload successful: {filename}")
                print(f"    Activity ID: {response}")
                return True
            else:
                print(f"  Upload failed: {filename} (no response)")
                return False
                
        except Exception as e:
            error_str = str(e)
            print(f"  Upload failed: {filename} - {e}")
            
            if 'already' in error_str.lower() or 'duplicate' in error_str.lower():
                print(f"  -> Activity already exists in Garmin Connect, skipping")
                return True
            
            if 'login' in error_str.lower() or 'auth' in error_str.lower() or '429' in error_str:
                print("  -> Retrying login...")
                self.client = None
                time.sleep(3)
                return self.upload_activity(file_data, filename)
            return False
            
        finally:
            if temp_path and os.path.exists(temp_path):
                os.unlink(temp_path)

class DropboxManager:
    def __init__(self):
        self.dbx = None
        self.refresh_token = Config.DROPBOX_REFRESH_TOKEN
        self.app_key = Config.DROPBOX_APP_KEY
        self.app_secret = Config.DROPBOX_APP_SECRET
        self.access_token = Config.DROPBOX_ACCESS_TOKEN
        
    def connect(self):
        try:
            if self.refresh_token and self.app_key and self.app_secret:
                self.dbx = dropbox.Dropbox(
                    oauth2_refresh_token=self.refresh_token,
                    app_key=self.app_key,
                    app_secret=self.app_secret
                )
                account = self.dbx.users_get_current_account()
                print(f"Dropbox connected (Refresh Token): {account.name.display_name}")
                return True
            
            if self.access_token:
                self.dbx = dropbox.Dropbox(self.access_token)
                account = self.dbx.users_get_current_account()
                print(f"Dropbox connected (Access Token): {account.name.display_name}")
                return True
                
            print("Dropbox connection failed: No valid token configured")
            return False
            
        except dropbox.exceptions.AuthError as e:
            print(f"Dropbox connection failed: AuthError - {e}")
            if 'expired_access_token' in str(e).lower():
                print("  -> Access Token expired, please switch to Refresh Token")
            return False
        except Exception as e:
            print(f"Dropbox connection failed: {e}")
            return False
    
    def list_activity_files(self, folder_path, recursive=True):
        if not self.dbx:
            if not self.connect():
                return []
        
        try:
            activity_files = []
            result = self.dbx.files_list_folder(folder_path, recursive=recursive)
            
            while True:
                for entry in result.entries:
                    if isinstance(entry, dropbox.files.FileMetadata):
                        if entry.name.lower().endswith(SUPPORTED_FORMATS):
                            activity_files.append(entry)
                
                if not result.has_more:
                    break
                result = self.dbx.files_list_folder_continue(result.cursor)
            
            return activity_files
            
        except dropbox.exceptions.ApiError as e:
            if 'not_found' in str(e).lower() or 'path' in str(e).lower():
                print(f"Dropbox folder not found: {folder_path}")
                print(f"  Please confirm Wahoo App is connected to Dropbox")
                print(f"  Check GitHub Secret DROPBOX_FOLDER path")
            else:
                print(f"List files failed: {e}")
            return []
        except Exception as e:
            print(f"List files failed: {e}")
            return []
    
    def list_all_folders(self, root_path='/'):
        if not self.dbx:
            return []
        try:
            result = self.dbx.files_list_folder(root_path)
            folders = [
                entry.path_display 
                for entry in result.entries 
                if isinstance(entry, dropbox.files.FolderMetadata)
            ]
            return folders
        except Exception:
            return []
    
    def download_file(self, file_path):
        try:
            _, response = self.dbx.files_download(file_path)
            return response.content
        except Exception as e:
            print(f"Download failed {file_path}: {e}")
            return None
    
    def move_file(self, from_path, to_folder):
        try:
            filename = os.path.basename(from_path)
            to_path = f"{to_folder}/{filename}"
            
            try:
                self.dbx.files_get_metadata(to_path)
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                name, ext = os.path.splitext(filename)
                to_path = f"{to_folder}/{name}_{timestamp}{ext}"
            except dropbox.exceptions.ApiError:
                pass
            
            try:
                self.dbx.files_get_metadata(to_folder)
            except dropbox.exceptions.ApiError:
                self.dbx.files_create_folder_v2(to_folder)
                print(f"  -> Created processed folder: {to_folder}")
            
            self.dbx.files_move_v2(from_path, to_path)
            print(f"  -> File moved to: {to_path}")
            return True
            
        except Exception as e:
            print(f"  Move file failed: {e}")
            return False

class WahooToGarminSync:
    def __init__(self):
        self.config = Config()
        self.state = SyncState()
        self.garmin = None
        self.dropbox = None
        
    def validate_config(self):
        required = {
            'GARMIN_EMAIL': self.config.GARMIN_EMAIL,
            'GARMIN_PASSWORD': self.config.GARMIN_PASSWORD,
        }
        
        has_dropbox = (
            (self.config.DROPBOX_REFRESH_TOKEN and self.config.DROPBOX_APP_KEY and self.config.DROPBOX_APP_SECRET)
            or self.config.DROPBOX_ACCESS_TOKEN
        )
        
        if not has_dropbox:
            print("Config error: Dropbox auth required")
            print("  Recommended: DROPBOX_REFRESH_TOKEN + DROPBOX_APP_KEY + DROPBOX_APP_SECRET")
            print("  Legacy: DROPBOX_ACCESS_TOKEN (expires in ~4h)")
            required['DROPBOX_AUTH'] = None
        
        missing = [k for k, v in required.items() if not v]
        if missing:
            print(f"Config error: Missing required Secrets: {', '.join(missing)}")
            return False
            
        return True
    
    def initialize(self):
        self.dropbox = DropboxManager()
        if not self.dropbox.connect():
            return False
        
        self.garmin = GarminUploader(
            self.config.GARMIN_EMAIL,
            self.config.GARMIN_PASSWORD,
            self.config.GARMIN_REGION
        )
        
        return True
    
    def sync(self):
        if not self.validate_config():
            return False
        
        if not self.initialize():
            return False
        
        print(f"\n{'='*50}")
        print(f"Sync started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Dropbox path: {self.config.DROPBOX_FOLDER}")
        print(f"Supported formats: {', '.join(SUPPORTED_FORMATS)}")
        print(f"Recursive search: {'Yes' if self.config.RECURSIVE_SEARCH else 'No'}")
        print(f"{'='*50}\n")
        
        activity_files = self.dropbox.list_activity_files(
            self.config.DROPBOX_FOLDER, 
            recursive=self.config.RECURSIVE_SEARCH
        )
        
        if not activity_files:
            print("No new activity files found")
            print("\nTroubleshooting:")
            
            root_folders = self.dropbox.list_all_folders('/')
            if root_folders:
                print("  Dropbox root folders:")
                for folder in root_folders:
                    print(f"    {folder}")
            
            sub_folders = self.dropbox.list_all_folders(self.config.DROPBOX_FOLDER)
            if sub_folders:
                print(f"\n  Subfolders under {self.config.DROPBOX_FOLDER}:")
                for folder in sub_folders:
                    print(f"    {folder}")
            
            self.print_summary()
            return True
        
        print(f"Found {len(activity_files)} activity files\n")
        
        if not self.garmin.login():
            return False
        
        success_count = 0
        skip_count = 0
        failed_count = 0
        
        for file_entry in activity_files:
            filename = file_entry.name
            file_path = file_entry.path_display
            
            print(f"Processing: {filename}")
            
            if self.state.is_processed(filename):
                print(f"  -> Skipped: already synced")
                skip_count += 1
                continue
            
            file_data = self.dropbox.download_file(file_path)
            if not file_data:
                failed_count += 1
                self.state.mark_failed(filename, "Download failed")
                continue
            
            if self.garmin.upload_activity(file_data, filename):
                self.state.mark_processed(filename)
                success_count += 1
                
                processed_folder = f"{self.config.DROPBOX_FOLDER}/processed"
                self.dropbox.move_file(file_path, processed_folder)
            else:
                failed_count += 1
                self.state.mark_failed(filename, "Upload failed")
            
            time.sleep(2)
        
        self.print_summary(success_count, skip_count, failed_count)
        return True
    
    def print_summary(self, success=0, skip=0, failed=0):
        print(f"\n{'='*50}")
        print("Sync Summary")
        print(f"{'='*50}")
        print(f"Success: {success}")
        print(f"Skipped: {skip}")
        print(f"Failed: {failed}")
        print(f"Total synced: {self.state.state['total_synced']}")
        print(f"Last sync: {self.state.state['last_sync']}")
        
        if self.state.state['failed_files']:
            print(f"\nRecent failures:")
            for fail in self.state.state['failed_files'][-5:]:
                print(f"  - {fail['filename']}: {fail['error']}")
        
        print(f"{'='*50}\n")

def main():
    try:
        sync = WahooToGarminSync()
        success = sync.sync()
        
        if not success:
            sys.exit(1)
            
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
