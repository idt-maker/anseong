import cv2
import numpy as np
import os
import argparse
from flask import Flask, Response, request, jsonify

# --- 전역 변수 설정 ---
roi_points = []
roi_mask = None
calib_points = []
PX_PER_METER_SCALE = None

# --- 시각화 설정 ---
PANEL_WIDTH = 640
PANEL_HEIGHT = 480

# =================================================================
# ✨ 1. [FIXED] 밀도 및 필터링 설정 수정 ✨
# =================================================================
# 화살표 밀도 (렉 걸리면 16 -> 24)
ARROW_STEP = 16
# ✨[FIX] 기준값을 0.5에서 0.1로 낮춰서 미세한 움직임도 감지
ARROW_MAGNITUDE_THRESHOLD = 0.1
# =================================================================

def handle_click(x, y):
    """
    마우스 클릭 이벤트를 처리합니다.
    """
    global roi_points, roi_mask, calib_points
    if x >= PANEL_WIDTH or y >= PANEL_HEIGHT: return

    if len(calib_points) < 2:
        calib_points.append((x, y))
    elif roi_mask is None:
        roi_points.append((x, y))

# =================================================================
# ✨ 2. 화살표 그리기 함수 (속도별 색상 구분)
# =================================================================
def draw_flow_arrows(frame, flow, step, magnitude_threshold, roi_mask=None):
    """
    '원본 프레임 복사본' 위에 속도별로 색상이 다른 화살표를 그립니다.
    """
    arrow_panel = frame.copy()
    h, w = frame.shape[:2]

    # 속도 임계값 (px/frame 기준)
    LOW_SPEED_THRESH = 0.2 # 기준값도 함께 낮춤
    HIGH_SPEED_THRESH = 0.5 # 기준값도 함께 낮춤

    for y in range(0, h, step):
        for x in range(0, w, step):
            if roi_mask is not None and roi_mask[y, x] == 0:
                continue

            dx, dy = flow[y, x].astype(np.float32)
            mag = np.sqrt(dx*dx + dy*dy)

            if mag > magnitude_threshold:
                start_point = (x, y)
                end_point = (int(x + dx), int(y + dy))

                # 속도에 따라 색상 결정
                if mag < LOW_SPEED_THRESH:
                    color = (255, 0, 0) # 느림 (파란색)
                elif mag < HIGH_SPEED_THRESH:
                    color = (0, 255, 0) # 중간 (녹색)
                else:
                    color = (0, 0, 255) # 빠름 (빨간색)

                cv2.arrowedLine(arrow_panel, start_point, end_point, color, 1, cv2.LINE_AA, 0, 0.3)

    return arrow_panel

# =================================================================
# ✨ 3. 개별 속도 텍스트 그리기 함수
# =================================================================
def draw_flow_speeds(frame, flow, step, magnitude_threshold, roi_mask, fps, px_per_m_scale):
    """
    '원본 프레임 복사본' 위에 'm/s' 단위의 개별 속도 텍스트를 그립니다.
    """
    speed_panel = frame.copy()
    h, w = frame.shape[:2]

    can_calc_mps = (px_per_m_scale is not None and px_per_m_scale > 0 and fps > 0)

    for y in range(0, h, step):
        for x in range(0, w, step):
            if roi_mask is not None and roi_mask[y, x] == 0:
                continue

            dx, dy = flow[y, x].astype(np.float32)
            mag_px_frame = np.sqrt(dx*dx + dy*dy)

            if mag_px_frame > magnitude_threshold:
                text = ""
                color = (255, 255, 255)

                if can_calc_mps:
                    mag_px_sec = mag_px_frame * fps
                    mag_mps = mag_px_sec / px_per_m_scale
                    text = f"{mag_mps:.1f}"

                    # m/s 속도에 따라 텍스트 색상 변경 (기준값 수정)
                    if mag_mps < 0.2: color = (255, 0, 0) # 파란색
                    elif mag_mps < 0.5: color = (0, 255, 0) # 녹색
                    else: color = (0, 0, 255) # 빨간색
                else:
                    text = f"{mag_px_frame:.1f}p"

                cv2.putText(speed_panel, text, (x, y - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1, cv2.LINE_AA)

    return speed_panel
# =================================================================

app = Flask(__name__)

def generate_frames(video_path):
    """
    비디오 스트림을 읽고 2x2 그리드로 표시합니다.
    """
    global roi_points, roi_mask, calib_points, PX_PER_METER_SCALE
    REAL_WORLD_DISTANCE_METERS = 5.0

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"오류: 비디오 소스를 열 수 없습니다. '{video_path}'를 확인하세요.")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps == 0 or fps is None: fps = 30.0
    print(f"비디오 FPS: {fps:.2f}")

    ret, frame1 = cap.read()
    if not ret:
        print("첫 프레임을 읽을 수 없습니다. 종료합니다.")
        return

    frame1 = cv2.resize(frame1, (PANEL_WIDTH, PANEL_HEIGHT))
    prvs = cv2.cvtColor(frame1, cv2.COLOR_BGR2GRAY)

    # --- ROI 파일 로드 ---
    if os.path.exists("roi_coords.txt"):
        try:
            loaded_points = np.loadtxt("roi_coords.txt", dtype=np.int32)
            if loaded_points.ndim == 1 and loaded_points.size >= 2:
                    roi_points = [tuple(loaded_points)]
            elif loaded_points.ndim > 1:
                roi_points = [tuple(point) for point in loaded_points]

            if len(roi_points) > 2:
                roi_mask = np.zeros((PANEL_HEIGHT, PANEL_WIDTH), dtype=np.uint8)
                cv2.fillPoly(roi_mask, [np.array(roi_points, dtype=np.int32)], 255)
                print(f"저장된 ROI {len(roi_points)}개 포인트를 불러왔습니다.")
            else:
                    roi_points = []
        except Exception as e:
            print(f"ROI 파일 로드 오류: {e}")
            roi_points = []
    # -------------------

    while True:
        ret, frame2 = cap.read()
        if not ret:
            print("스트림 끝. 종료합니다.")
            break

        frame2 = cv2.resize(frame2, (PANEL_WIDTH, PANEL_HEIGHT))
        frame_with_ui = frame2.copy()
        next_gray = cv2.cvtColor(frame2, cv2.COLOR_BGR2GRAY)

        flow = cv2.calcOpticalFlowFarneback(prvs, next_gray, None, 0.5, 3, 15, 3, 5, 1.2, 0)
        mag, _ = cv2.cartToPolar(flow[...,0], flow[...,1])

        avg_speed_px_frame = 0.0

        # (패널 2: 방향 화살표)
        arrow_panel = draw_flow_arrows(frame2, flow, ARROW_STEP, ARROW_MAGNITUDE_THRESHOLD, roi_mask)

        # (패널 3: 개별 속도 텍스트)
        speed_panel = draw_flow_speeds(frame2, flow, ARROW_STEP, ARROW_MAGNITUDE_THRESHOLD,
                                        roi_mask, fps, PX_PER_METER_SCALE)

        # (패널 4: UI 패널)
        ui_panel = np.zeros((PANEL_HEIGHT, PANEL_WIDTH, 3), dtype=np.uint8)

        # (패널 1) 원본 영상에 P1/P2/ROI 선 그리기
        if len(calib_points) == 2:
            p1, p2 = calib_points
            cv2.line(frame_with_ui, p1, p2, (255, 0, 0), 2)
            cv2.circle(frame_with_ui, p1, 5, (255, 0, 0), -1)
            cv2.putText(frame_with_ui, "P1", (p1[0] + 10, p1[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)
            cv2.circle(frame_with_ui, p2, 5, (255, 0, 0), -1)
            cv2.putText(frame_with_ui, "P2", (p2[0] + 10, p2[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)

            if PX_PER_METER_SCALE is None:
                pixel_distance = np.linalg.norm(np.array(p1) - np.array(p2))
                if REAL_WORLD_DISTANCE_METERS > 0:
                    PX_PER_METER_SCALE = pixel_distance / REAL_WORLD_DISTANCE_METERS
                    print(f"스케일 보정 완료: {PX_PER_METER_SCALE:.2f} px/m")
                else:
                    PX_PER_METER_SCALE = 0

        elif len(calib_points) == 1:
            p1 = calib_points[0]
            cv2.circle(frame_with_ui, p1, 5, (255, 0, 0), -1)
            cv2.putText(frame_with_ui, "P1", (p1[0] + 10, p1[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 0, 0), 2)

        # ROI 처리 및 속도 계산
        if roi_mask is not None:
            masked_mag = mag[roi_mask == 255]
            if masked_mag.size > 0:
                avg_speed_px_frame = np.mean(masked_mag)
            cv2.polylines(frame_with_ui, [np.array(roi_points, dtype=np.int32)], True, (0, 255, 0), 2)
            cv2.polylines(arrow_panel, [np.array(roi_points, dtype=np.int32)], True, (0, 255, 0), 2)
            cv2.polylines(speed_panel, [np.array(roi_points, dtype=np.int32)], True, (0, 255, 0), 2)

        elif len(calib_points) == 2:
            if len(roi_points) > 0:
                for point in roi_points:
                    cv2.circle(frame_with_ui, point, 5, (0, 0, 255), -1)
                if len(roi_points) > 1:
                    cv2.polylines(frame_with_ui, [np.array(roi_points, dtype=np.int32)], False, (0, 0, 255), 2)
            avg_speed_px_frame = np.mean(mag)
        else:
            avg_speed_px_frame = np.mean(mag)

        # (패널 4) UI 패널에 텍스트 그리기
        if len(calib_points) < 2:
            ui_text = f"STEP 1: Click 2 points on [Original] panel"
            ui_text2 = f"(Real Distance: {REAL_WORLD_DISTANCE_METERS}m)"
            cv2.putText(ui_panel, ui_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(ui_panel, ui_text2, (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)
        elif roi_mask is None:
            ui_text = "STEP 2: Click 3+ points on [Original] panel"
            ui_text2 = "Press 's' to confirm ROI"
            cv2.putText(ui_panel, ui_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
            cv2.putText(ui_panel, ui_text2, (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        else:
                ui_text = "STATUS: Monitoring..."
                cv2.putText(ui_panel, ui_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        y_offset = 120
        if PX_PER_METER_SCALE is not None and PX_PER_METER_SCALE > 0:
            avg_speed_px_sec = avg_speed_px_frame * fps
            avg_speed_mps = avg_speed_px_sec / PX_PER_METER_SCALE
            speed_text_mps = f"Avg. Speed: {avg_speed_mps:.2f} m/s"
            scale_text = f"Scale: {PX_PER_METER_SCALE:.2f} px/m (OK)"
            cv2.putText(ui_panel, speed_text_mps, (20, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2, cv2.LINE_AA)
            cv2.putText(ui_panel, scale_text, (20, y_offset + 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1, cv2.LINE_AA)
        else:
            speed_text_mps = "Avg. Speed: CALIBRATE FIRST"
            cv2.putText(ui_panel, speed_text_mps, (20, y_offset), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)

        key_text_y_start = PANEL_HEIGHT - 120
        cv2.putText(ui_panel, "Key Controls:", (20, key_text_y_start), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(ui_panel, "[q] Quit", (20, key_text_y_start + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(ui_panel, "[s] Save ROI", (20, key_text_y_start + 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(ui_panel, "[r] Reset ROI Only", (20, key_text_y_start + 80), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
        cv2.putText(ui_panel, "[c] Reset ALL (Scale & ROI)", (20, key_text_y_start + 105), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        # 4개 패널 합치기
        top_row = np.hstack((frame_with_ui, arrow_panel))
        bottom_row = np.hstack((speed_panel, ui_panel))
        combined_frame = np.vstack((top_row, bottom_row))

        (flag, encodedImage) = cv2.imencode(".jpg", combined_frame)
        if not flag:
            continue
        yield(b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' +
            bytearray(encodedImage) + b'\r\n')

        prvs = next_gray

    cap.release()

@app.route("/video_feed")
def video_feed():
    return Response(generate_frames(app.config['VIDEO_PATH']),
                    mimetype = "multipart/x-mixed-replace; boundary=frame")

@app.route('/click', methods=['POST'])
def click():
    data = request.get_json()
    x = int(data['x'])
    y = int(data['y'])
    handle_click(x, y)
    return jsonify(success=True)

@app.route('/save_roi', methods=['POST'])
def save_roi():
    global roi_mask
    if len(calib_points) < 2:
        return jsonify(success=False, message="오류: 스케일 보정을 먼저 완료해야 합니다.")
    elif len(roi_points) > 2:
        roi_mask = np.zeros((PANEL_HEIGHT, PANEL_WIDTH), dtype=np.uint8)
        points = np.array(roi_points, dtype=np.int32)
        cv2.fillPoly(roi_mask, [points], 255)
        np.savetxt("roi_coords.txt", points, fmt="%d")
        return jsonify(success=True, message="ROI가 설정되었습니다.")
    else:
        return jsonify(success=False, message="ROI를 생성하려면 최소 3개 이상의 점이 필요합니다.")

@app.route('/reset_roi', methods=['POST'])
def reset_roi():
    global roi_points, roi_mask
    roi_points = []
    roi_mask = None
    if os.path.exists("roi_coords.txt"):
        os.remove("roi_coords.txt")
    return jsonify(success=True, message="ROI가 초기화되었습니다.")

@app.route('/reset_all', methods=['POST'])
def reset_all():
    global roi_points, roi_mask, calib_points, PX_PER_METER_SCALE
    roi_points = []
    roi_mask = None
    calib_points = []
    PX_PER_METER_SCALE = None
    if os.path.exists("roi_coords.txt"):
        os.remove("roi_coords.txt")
    return jsonify(success=True, message="모든 설정(스케일, ROI)이 초기화되었습니다.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Video stream analysis')
    parser.add_argument('--video', type=str, required=True, help='Path to the video file')
    args = parser.parse_args()

    app.config['VIDEO_PATH'] = args.video
    app.run(host='0.0.0.0', port=8080, debug=True, threaded=True, use_reloader=False)