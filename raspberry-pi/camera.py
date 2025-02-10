import os
import cv2
import tkinter as tk
from tkinter import messagebox
from PIL import Image, ImageTk
from google.cloud import storage
from picamera2 import Picamera2

# Google Cloud Storageの認証情報を環境変数でセット
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"/home/sharelab/cameraToStorage/CameraToStorage/json/sharelabai-hackathon-b18ad87596b3.json"

def upload_to_bucket(bucket_name, source_file_path, destination_blob_name):
    """
    GCSバケットにファイルをアップロードするサンプル関数
    """
    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(destination_blob_name)
    blob.upload_from_filename(source_file_path)
    print(f"File {source_file_path} uploaded to gs://{bucket_name}/{destination_blob_name}.")

class CameraApp:
    def __init__(self, master):
        self.master = master
        self.master.title("Camera Capture and Upload (Picamera2版)")
        
        # ウィンドウサイズを1920x1080に設定し、最小サイズも指定
        self.master.geometry("1920x1080")
        self.master.minsize(640, 480)
        
        # フレームを作成してパッキング
        self.main_frame = tk.Frame(self.master)
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # GCSバケット情報
        self.bucket_name = "camera_storage11111"
        self.destination_blob_name = "uploads/captured_photo.jpg"
        
        # Picamera2でカメラを初期化
        try:
            self.picam2 = Picamera2()
            # プレビュー用の設定（1920x1080に最適化）
            config = self.picam2.create_preview_configuration(main={"size": (1920, 1080)})
            self.picam2.configure(config)
            self.picam2.start()
        except Exception as e:
            messagebox.showerror("Error", f"カメラの初期化に失敗しました: {e}")
            return

        # ボタン用フレームを先に作成（高さを固定）
        button_frame = tk.Frame(self.main_frame, height=60)
        button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=10)
        button_frame.pack_propagate(False)  # フレームサイズを固定
        
        # カメラ映像を表示するためのフレームとラベル
        video_frame = tk.Frame(self.main_frame)
        video_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(10, 0))
        
        self.label_video = tk.Label(video_frame)
        self.label_video.pack(fill=tk.BOTH, expand=True)
        
        # 撮影用ボタン
        self.capture_button = tk.Button(
            button_frame,
            text="撮影してアップロード",
            command=self.capture_and_upload,
            height=2
        )
        self.capture_button.pack(pady=5)
        
        # リアルタイムでフレーム更新開始
        self.update_frame()

    def update_frame(self):
        """
        Picamera2から取得したカメラ映像を更新してtkinterのラベルに表示する
        """
        try:
            frame = self.picam2.capture_array()
        except Exception as e:
            self.master.after(10, self.update_frame)
            return

        # ウィンドウがまだ作成されていない場合のデフォルトサイズ
        window_width = self.label_video.winfo_width() or 1920
        window_height = self.label_video.winfo_height() or 1080
        
        # サイズが0以下の場合はデフォルト値を使用
        window_width = max(window_width, 640)
        window_height = max(window_height, 480)

        # フレームをウィンドウサイズに合わせてリサイズ
        img = Image.fromarray(frame)
        
        # アスペクト比を計算
        aspect_ratio = frame.shape[1] / frame.shape[0]
        target_ratio = window_width / window_height
        
        if aspect_ratio > target_ratio:
            # 幅に合わせてリサイズ
            new_width = window_width
            new_height = int(window_width / aspect_ratio)
        else:
            # 高さに合わせてリサイズ
            new_height = window_height
            new_width = int(window_height * aspect_ratio)
        
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        imgtk = ImageTk.PhotoImage(image=img)
        self.label_video.imgtk = imgtk
        self.label_video.configure(image=imgtk)

        # 定期的に再更新（33ミリ秒 ≒ 30FPS）
        self.master.after(33, self.update_frame)

    def capture_and_upload(self):
        """
        現在のフレームを取得してローカルに保存し、GCSにアップロードする
        """
        try:
            frame = self.picam2.capture_array()
        except Exception as e:
            messagebox.showerror("Error", f"カメラから画像を取得できませんでした: {e}")
            return

        local_photo_path = r"/home/sharelab/cameraToStorage/captured_photo.jpg"
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        cv2.imwrite(local_photo_path, frame_bgr)

        try:
            upload_to_bucket(
                bucket_name=self.bucket_name,
                source_file_path=local_photo_path,
                destination_blob_name=self.destination_blob_name
            )
            messagebox.showinfo("Success", "写真をアップロードしました。")
        except Exception as e:
            messagebox.showerror("Error", f"アップロードに失敗しました: {e}")

def main():
    root = tk.Tk()
    app = CameraApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()