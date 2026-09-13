import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from mailer import send_error_mail


JST = ZoneInfo("Asia/Tokyo")


def main():

    now = datetime.now(JST)

    print(
        "1分足保存ジョブ開始:",
        now.isoformat()
    )

    # ペーパートレーダーとは完全分離。
    # 正式な1分足取得・保存処理は
    # このジョブ側だけに接続する。

    print(
        "1分足保存ジョブ正常終了:",
        datetime.now(JST).isoformat()
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        details = traceback.format_exc()

        try:

            send_error_mail(
                "1分足データ保存",
                str(e),
                details
            )

        finally:

            print(details)
            sys.exit(1)
