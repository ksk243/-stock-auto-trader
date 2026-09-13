import os
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr


def send_mail(subject, body):

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))

    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]

    mail_from = os.environ["MAIL_FROM"]
    mail_to = os.environ["MAIL_TO"]

    msg = MIMEText(body, "plain", "utf-8")

    msg["Subject"] = Header(subject, "utf-8")

    msg["From"] = formataddr(
        (
            str(Header("FIX17 自動売買", "utf-8")),
            mail_from,
        )
    )

    msg["To"] = mail_to

    with smtplib.SMTP(
        smtp_host,
        smtp_port,
        timeout=30
    ) as smtp:

        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()

        smtp.login(
            smtp_user,
            smtp_password
        )

        smtp.sendmail(
            mail_from,
            [mail_to],
            msg.as_string()
        )


def send_error_mail(
    job_name,
    error_message,
    details=""
):

    subject = (
        f"【FIX17 緊急】"
        f"{job_name}で異常が発生しました"
    )

    body = (
        "FIX17 自動運用システム\n\n"
        "【異常を検出しました】\n\n"
        f"処理：\n{job_name}\n\n"
        f"エラー内容：\n{error_message}\n\n"
        f"詳細：\n{details if details else 'なし'}\n\n"
        "この処理は正常終了していません。\n"
        "GitHub Actionsの実行履歴を確認してください。"
    )

    send_mail(
        subject,
        body
    )
