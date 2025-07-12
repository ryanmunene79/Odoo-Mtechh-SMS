from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import logging
from uuid import uuid4

_logger = logging.getLogger("mtech_sms")


class MtechSmsProvider(models.Model):
    _name = "mtech.sms.provider"
    _description = "MTech SMS Provider"

    name = fields.Char(required=True, default="MTech SMS")
    active = fields.Boolean(default=True)
    mtech_username = fields.Char(string="API Username", required=True)
    mtech_password = fields.Char(string="API Password", required=True)
    mtech_url = fields.Char(
        string="API URL", default="https://api.mtechsms.com", required=True
    )
    mtech_sender_id = fields.Char(string="Sender ID", required=True)
    dlr_url = fields.Char(
        string="Delivery Report URL",
        default=lambda self: self._default_dlr_url(),
        required=True,
    )

    def _default_dlr_url(self):
        """Generate default DLR callback URL"""
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        return f"{base_url}/mtech/sms/delivery"

    def _get_mtech_token(self):
        """Get authentication token from MTech API"""
        try:
            _logger.info("Authenticating with MTech API...")
            auth_url = f"{self.mtech_url}/index.php/auth/token"
            auth_data = {
                "username": self.mtech_username,
                "password": self.mtech_password,
            }

            auth_response = requests.post(auth_url, json=auth_data, timeout=30)

            if auth_response.status_code == 200:
                return auth_response.json().get("data", {}).get("token")
            _logger.error("Authentication failed: %s", auth_response.text)
            return None

        except Exception as e:
            _logger.exception("Token acquisition failed")
            return None

    def _send_single_sms(self, token, number, message):
        try:
            message_id = str(uuid4())
            send_url = f"{self.mtech_url}/index.php/messaging/send"
            sms_data = {
                "message": message,
                "sender": self.mtech_sender_id,
                "message_type": "Transactional",
                "msisdns": [number],
                "message_id": message_id,
                "dlr_url": self.dlr_url,
            }

            _logger.info("SMS API Payload: %s", sms_data)  # Log the payload

            send_response = requests.post(
                send_url,
                json=sms_data,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                timeout=30,
            )

            _logger.info(
                "Complete API Response: %s", send_response.text
            )  # Full response log

            if send_response.status_code == 200:
                response_data = send_response.json()
                _logger.info("API Response Data: %s", response_data)  # Parsed response
                if response_data.get("status") == 200:
                    return {
                        "success": True,
                        "message_id": message_id,
                        "raw_response": response_data,
                    }
                _logger.error("API reported failure: %s", response_data)

            return {
                "error": send_response.text,
                "status_code": send_response.status_code,
                "raw_response": send_response.json() if send_response.content else None,
            }

        except Exception as e:
            _logger.exception("Failed to send SMS: %s", str(e))
            return {"error": str(e)}

    def send_sms_batch(self, messages):
        """Send batch of SMS messages"""
        _logger.info("Starting batch send of %d messages", len(messages))

        token = self._get_mtech_token()
        if not token:
            _logger.error("Cannot send batch - no authentication token")
            return [{"error": "Authentication failed"} for _ in messages]

        results = []
        for message in messages:
            result = self._send_single_sms(token, message["number"], message["content"])
            results.append(result)
            if "error" in result:
                _logger.error(
                    "Failed to send to %s: %s", message["number"], result["error"]
                )

        _logger.info(
            "Batch send completed. Success: %d/%d",
            sum(1 for r in results if "success" in r),
            len(messages),
        )
        return results

    def _process_queue_batch(self, batch_size=50):
        """Process SMS queue in larger batches"""
        domain = [("state", "=", "outgoing")]
        messages = self.search(domain, limit=batch_size)

        if not messages:
            return True

        numbers = messages.mapped("number")
        content = messages[0].body  # Batch requires identical content

        try:
            results = self._send_sms(numbers, content)
            for sms, result in zip(messages, results):
                sms.write(
                    {
                        "state": "sent" if result["success"] else "error",
                        "mtech_message_id": result.get("message_id"),
                        "mtech_sent_date": fields.Datetime.now(),
                    }
                )
            return len(messages)
        except Exception as e:
            _logger.error("Queue processing failed: %s", str(e))
            return False


class MtechDeliveryController(models.AbstractModel):
    _name = "mtech.delivery.controller"
    _description = "MTech Delivery Report Controller"

    @api.model
    def _handle_delivery_report(self, **kwargs):
        """Handle delivery reports from MTech"""
        message_id = kwargs.get("message_id")
        status = kwargs.get("status")

        sms = self.env["sms.sms"].search([("mtech_message_id", "=", message_id)])
        if sms:
            if status.lower() == "delivered":
                sms.write({"state": "delivered"})
            else:
                sms.write({"state": "error"})
            return "OK"
        return "Message not found"


class MtechSmsProvider(models.Model):
    _inherit = "mtech.sms.provider"

    def test_sms_sending(self):
        self.ensure_one()
        test_number = self.env.context.get(
            "test_number", "+254718937403"
        )  # Default test number
        result = self._send_single_sms(
            self._get_mtech_token(), test_number, "Test SMS\n"
        )
        if result.get("success"):
            raise UserError(_("Test SMS sent successfully!"))
        else:
            raise UserError(
                _("Failed to send test SMS: %s") % result.get("error", "Unknown error")
            )


class Mailing(models.Model):
    _inherit = "mailing.mailing"

    def action_send_test_sms(self):
        self.ensure_one()
        if self.mailing_type != "sms":
            return super().action_send_test_sms()

        mtech_provider = self.env["mtech.sms.provider"].search(
            [("active", "=", True)], limit=1
        )
        if not mtech_provider:
            raise UserError(_("No active MTech SMS provider found"))

        # CORRECTED: Use 'test_mobile_numbers' to get the recipients
        numbers = self.env.context.get("test_mobile_numbers")
        if not numbers:
            raise UserError(_("Please specify test mobile numbers in the wizard."))

        messages = [
            {"number": num.strip(), "content": self.body_plaintext}
            for num in numbers.split(",")
        ]
        results = mtech_provider.send_sms_batch(messages)

        if all("success" in r for r in results):
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Success"),
                    "message": _("Test SMS successfully sent"),
                    "type": "success",
                },
            }
        raise UserError(
            _("Failed to send test SMS: %s")
            % "\n".join(
                r.get("error", "Unknown error") for r in results if "error" in r
            )
        )


class Http(models.AbstractModel):
    _inherit = "ir.http"

    @classmethod
    def _register_delivery_route(cls):
        """Register delivery report route"""
        cls.routes.append(
            (
                "/mtech/sms/delivery",
                "mtech.delivery.controller",
                "_handle_delivery_report",
                ["POST"],
            )
        )
        return True

    @classmethod
    def _post_init(cls):
        """Register route after initialization"""
        super()._post_init()
        cls._register_delivery_route()


class SmsSms(models.Model):
    _inherit = "sms.sms"

    # Add tracking fields to the model
    mtech_message_id = fields.Char(string="MTech Message ID")
    mtech_sent_date = fields.Datetime(string="Sent Date")

    def _send(self, **kwargs):
        """Override SMS sending to use MTech API"""
        _logger.info("Processing SMS send request for %d messages", len(self))

        mtech_provider = self.env["mtech.sms.provider"].search(
            [("active", "=", True)], limit=1
        )

        if not mtech_provider:
            _logger.warning("No active MTech provider - falling back to default")
            return super()._send(**kwargs)

        messages = [{"number": sms.number, "content": sms.body} for sms in self]

        results = mtech_provider.send_sms_batch(messages)

        for sms, result in zip(self, results):
            if "success" in result:
                sms.write(
                    {
                        "state": "sent",
                        "mtech_message_id": result[
                            "message_id"
                        ],  # Use our custom field
                        "mtech_sent_date": fields.Datetime.now(),  # Use our custom field
                    }
                )
            else:
                sms.write({"state": "error", "mtech_sent_date": fields.Datetime.now()})

        return all("success" in r for r in results)


class MassSMSTest(models.TransientModel):
    _inherit = "mailing.sms.test"

    def action_send_sms(self):
        """Override the action that sends the test SMS to use the custom provider."""
        mtech_provider = self.env["mtech.sms.provider"].search(
            [("active", "=", True)], limit=1
        )
        if not mtech_provider:
            _logger.warning(
                "MTech provider not active, falling back to default test send."
            )
            return super().action_send_sms()

        _logger.info("Intercepting Test SMS for Mass Mailing via MTech provider.")

        # 'self.numbers' contains the comma-separated phone numbers from the wizard
        numbers = [num.strip() for num in self.numbers.split(",")]
        # 'self.mailing_id' is the related mass mailing record
        message_body = self.mailing_id.body_plaintext

        messages = [{"number": num, "content": message_body} for num in numbers]

        results = mtech_provider.send_sms_batch(messages)

        # You can add a notification here if you wish, but for now, we just log it
        if all(r.get("success") for r in results):
            _logger.info("Successfully sent test SMS via MTech.")
        else:
            _logger.error(
                "Failed to send some test SMS via MTech. Results: %s", results
            )

        # Return True to close the wizard
        return True
