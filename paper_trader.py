      - name: Send result email

        uses: dawidd6/action-send-mail@v3

        with:

          server_address: ${{ secrets.SMTP_HOST }}

          server_port: ${{ secrets.SMTP_PORT }}

          username: ${{ secrets.SMTP_USER }}

          password: ${{ secrets.SMTP_PASSWORD }}

          subject: "v33.20 Paper Trader ${{ inputs.run_mode }}"

          to: ${{ secrets.MAIL_TO }}

          from: ${{ secrets.MAIL_USER }}

          secure: true

          body: file://latest_result.txt
