import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from mailer import send_mail, send_error_mail


JST = ZoneInfo("Asia/Tokyo")


def main():

    now = datetime.now(JST)

    # FIX17正式ロジックは
    # FIX17_OFFICIAL_FULL_SOURCE.py を親とする。
    # ここでは勝手に再構築しない。

    subject = (
        f"FIX17 本日の運用結果 "
        f"{now:%Y/%m/%d}"
    )

    body = (
        "FIX17 ペーパートレーダー\n\n"
        f"日付：{now:%Y/%m/%d}\n\n"
        "状態：GitHub実行環境 正常\n\n"
        "正式ソース：\n"
        "FIX17_OFFICIAL_FULL_SOURCE.py\n"
    )

    send_mail(
        subject,
        body
    )


if __name__ == "__main__":

    try:

        main()

    except Exception as e:

        details = traceback.format_exc()

        try:

            send_error_mail(
                "ペーパートレーダー",
                str(e),
                details
            )

        finally:

            print(details)
            sys.exit(1)
