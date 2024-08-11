import re

def parse_user_agent(user_agent):
    # 운영 체제 정보
    os_patterns = [
        (r'Windows NT 10\.0', 'Windows 10'),
        (r'Windows NT 6\.3', 'Windows 8.1'),
        (r'Windows NT 6\.2', 'Windows 8'),
        (r'Windows NT 6\.1', 'Windows 7'),
        (r'Windows NT 6\.0', 'Windows Vista'),
        (r'Windows NT 5\.1', 'Windows XP'),
        (r'Windows NT 5\.0', 'Windows 2000'),
        (r'Mac OS X (\d+[._]\d+[._]\d+)', 'macOS {}'),
        (r'Mac OS X (\d+[._]\d+)', 'macOS {}'),
        (r'iPhone OS (\d+[._]\d+)', 'iOS {}'),
        (r'iPad.*OS (\d+[._]\d+)', 'iPadOS {}'),
        (r'Android (\d+\.\d+)', 'Android {}'),
        (r'Linux', 'Linux'),
        (r'CrOS', 'Chrome OS'),
        (r'Windows Phone (\d+\.\d+)', 'Windows Phone {}'),
        (r'SymbianOS/(\d+\.\d+)', 'SymbianOS {}'),
        (r'BlackBerry', 'BlackBerry OS'),
        (r'BB10', 'BlackBerry 10'),
        (r'Tizen/(\d+\.\d+)', 'Tizen {}'),
        (r'KaiOS/(\d+\.\d+)', 'KaiOS {}'),
    ]

    # 브라우저 정보
    browser_patterns = [
        (r'MSIE (\d+\.\d+)', 'Internet Explorer {}'),
        (r'Trident/.*rv:(\d+\.\d+)', 'Internet Explorer {}'), # IE 11
        (r'Edge/(\d+\.\d+)', 'Microsoft Edge Legacy {}'),
        (r'Edg/(\d+\.\d+)', 'Microsoft Edge {}'),
        (r'Firefox/(\d+\.\d+)', 'Firefox {}'),
        (r'Chrome/(\d+\.\d+)', 'Chrome {}'),
        (r'OPR/(\d+\.\d+)', 'Opera {}'),
        (r'Version/(\d+\.\d+) .*Safari/', 'Safari {}'),
        (r'Opera/(\d+\.\d+)', 'Opera {}'),
        (r'CriOS/(\d+\.\d+)', 'Chrome iOS {}'),
        (r'FxiOS/(\d+\.\d+)', 'Firefox iOS {}'),
        (r'SamsungBrowser/(\d+\.\d+)', 'Samsung Internet {}'),
        (r'UCBrowser/(\d+\.\d+)', 'UC Browser {}'),
        (r'YaBrowser/(\d+\.\d+)', 'Yandex Browser {}'),
        (r'Vivaldi/(\d+\.\d+)', 'Vivaldi {}'),
        (r'Seamonkey/(\d+\.\d+)', 'SeaMonkey {}'),
        (r'Silk/(\d+\.\d+)', 'Amazon Silk {}'),
        (r'Puffin/(\d+\.\d+)', 'Puffin {}'),
        (r'BaiduBrowser/(\d+\.\d+)', 'Baidu Browser {}'),
        (r'QQBrowser/(\d+\.\d+)', 'QQ Browser {}'),
        (r'SogouMobileBrowser/(\d+\.\d+)', 'Sogou Mobile Browser {}'),
        (r'MiuiBrowser/(\d+\.\d+)', 'Miui Browser {}'),
    ]

    # 기기 정보
    device_patterns = [
        (r'iPhone', 'iPhone'),
        (r'iPad', 'iPad'),
        (r'iPod', 'iPod'),
        (r'Android.*Mobile', 'Android Mobile'),
        (r'Android', 'Android Tablet'),
        (r'Windows Phone', 'Windows Phone'),
        (r'Windows NT', 'Desktop PC'),
        (r'Macintosh', 'Macintosh'),
        (r'CrOS', 'Chromebook'),
        (r'Linux', 'Linux Device'),
        (r'Nokia', 'Nokia Phone'),
        (r'BlackBerry', 'BlackBerry Device'),
        (r'BB10', 'BlackBerry 10 Device'),
        (r'PlayStation (\d+)', 'PlayStation {}'),
        (r'Xbox One', 'Xbox One'),
        (r'Xbox', 'Xbox'),
        (r'Nintendo Switch', 'Nintendo Switch'),
        (r'Nintendo 3DS', 'Nintendo 3DS'),
        (r'Nintendo WiiU', 'Nintendo Wii U'),
        (r'Nintendo Wii', 'Nintendo Wii'),
        (r'Sony Bravia', 'Sony Bravia TV'),
        (r'SmartTV', 'Smart TV'),
        (r'Valve Steam', 'Steam Device'),
        (r'OculusBrowser', 'Oculus Device'),
        (r'HTC.*VR', 'HTC VR Device'),
        (r'Sony.*VR', 'Sony VR Device'),
        (r'Lenovo.*VR', 'Lenovo VR Device'),
    ]

    os_info = "Unknown OS"
    browser_info = "Unknown Browser"
    device_info = "Unknown Device"

    # OS 정보 파싱
    for pattern, os_name in os_patterns:
        match = re.search(pattern, user_agent)
        if match:
            if '{}' in os_name:
                os_info = os_name.format(match.group(1).replace('_', '.'))
            else:
                os_info = os_name
            break

    # 브라우저 정보 파싱
    for pattern, browser_name in browser_patterns:
        match = re.search(pattern, user_agent)
        if match:
            browser_info = browser_name.format(match.group(1))
            break

    # 기기 정보 파싱
    for pattern, device_name in device_patterns:
        if re.search(pattern, user_agent):
            device_info = device_name
            break

    return f"{device_info}, {os_info}, {browser_info}"