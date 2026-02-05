# SV2 Linux Bridge

Linux에서 **Synthesizer V Studio 2 Pro**를 실행하기 위한 OAuth 인증 브릿지입니다.

Wine/Bottles 환경에서 SV2의 OAuth 로그인 문제를 해결합니다.

## 문제점

SV2 Pro는 Dreamtonics 계정 로그인에 내장 WebView를 사용합니다. Wine에서는 이 WebView가 제대로 작동하지 않아 로그인이 불가능합니다.

## 해결책

이 브릿지는:
1. `dreamtonics-svstudio2://` 프로토콜을 Linux에서 처리
2. OAuth 콜백을 가로채서 SV2에 전달
3. SV2가 자체적으로 토큰 교환을 완료하도록 지원

## 요구사항

- Linux (Arch, Ubuntu, Fedora 등)
- [Bottles](https://usebottles.com/) (Flatpak 권장)
- Python 3.8+
- Firefox (또는 다른 브라우저)

## 빠른 시작

### 1. Bottles에서 SV2 설치

```bash
# Bottles 설치 (Flatpak)
flatpak install flathub com.usebottles.bottles

# 새 bottle 생성 (예: svstudio64)
# Bottles GUI에서 Gaming 환경으로 생성
# SV2 설치 파일 실행
```

### 2. Auth Bridge 설치

```bash
git clone https://github.com/anxrch/sv2-linux-bridge.git
cd sv2-linux-bridge

# 가상환경 생성 및 활성화
python -m venv .venv
source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 실행 스크립트 설치
./install.sh
```

### 3. Firefox 프로토콜 핸들러 설정

Firefox의 `handlers.json` (보통 `~/.mozilla/firefox/*.default-release/handlers.json`) 편집:

```json
{
  "schemes": {
    "dreamtonics-svstudio2": {
      "action": 2,
      "handlers": [
        {
          "name": "SV2 Auth Bridge",
          "path": "/home/YOUR_USER/.local/bin/sv2-auth-bridge"
        }
      ]
    }
  }
}
```

### 4. 사용 방법

```bash
# 1. Auth Bridge 서버 시작
sv2-auth-bridge --port 8888

# 2. Bottles에서 SV2 실행
flatpak run com.usebottles.bottles -b svstudio64 -e synthv-studio.exe

# 3. SV2에서 로그인 버튼 클릭
# 4. Firefox에서 Dreamtonics 계정으로 로그인
# 5. 자동으로 SV2에 인증 정보 전달
```

## 성능 최적화 (NVIDIA + Wayland)

Bottles 환경변수에 추가:

```
__GL_SYNC_TO_VBLANK=0
GTK_IM_MODULE=ibus
QT_IM_MODULE=ibus
XMODIFIERS=@im=ibus
```

### GameMode & Gamescope (선택)

```bash
# GameMode 설치
sudo pacman -S gamemode lib32-gamemode  # Arch
sudo apt install gamemode  # Ubuntu

# Gamescope 설치 (Flatpak)
flatpak install flathub org.freedesktop.Platform.VulkanLayer.gamescope

# Bottles에서 GameMode 활성화
```

## 한글 입력

Bottles 환경변수에 입력기 설정 추가 (ibus 사용 시):

```
GTK_IM_MODULE=ibus
QT_IM_MODULE=ibus
XMODIFIERS=@im=ibus
```

## 문제 해결

### 로그인 후 SV2가 반응하지 않음

1. Auth Bridge 서버가 실행 중인지 확인: `tail -f /tmp/auth_bridge.log`
2. `license/cb` 파일이 생성되었는지 확인
3. SV2 재시작

### 프레임 드랍

1. `__GL_SYNC_TO_VBLANK=0` 환경변수 추가
2. GameMode 활성화
3. Gamescope 사용

### 한글이 입력되지 않음

Bottles 환경변수에 입력기 설정 추가 (위 참조)

## 프로젝트 구조

```
sv2-linux-bridge/
├── src/
│   └── auth_bridge/
│       └── server.py      # 메인 인증 브릿지 서버
├── install.sh             # 설치 스크립트
├── requirements.txt       # Python 의존성
└── README.md
```

## 라이선스

GPL-3.0 License

## 기여

이슈와 PR 환영합니다!
