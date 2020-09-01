import base64
import collections
import logging
from rest_framework import serializers

from trade_portal.documents.models import Document, FTA, Party, OaDetails

logger = logging.getLogger(__name__)


def dict_merge(dct, merge_dct):
    """
    Recursive dict merge. Inspired by :meth:``dict.update()``, instead of
    updating only top-level keys, dict_merge recurses down into dicts nested
    to an arbitrary depth, updating keys. The ``merge_dct`` is merged into
    ``dct``.
    :param dct: dict onto which the merge is executed
    :param merge_dct: dct merged into dct
    :return: None
    """
    for k, v in merge_dct.items():
        if (k in dct and isinstance(dct[k], dict)
                and isinstance(merge_dct[k], collections.Mapping)):
            dict_merge(dct[k], merge_dct[k])
        else:
            dct[k] = merge_dct[k]


class CertificateSerializer(serializers.Serializer):

    class Meta:
        model = Document
        fields = (
            'id', 'name',
        )

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        self.org = kwargs.pop("org")
        super().__init__(*args, **kwargs)

    def to_representation(self, instance):
        """
        We just proxy the model's raw_certificate_data, replacing some
        critical fields by the our-generated values (so users don't invent
        their own IDs for example)
        """
        if not instance.raw_certificate_data:
            # this certificate has been created using UI
            # so has no rendered data, TODO: render it
            data = {
                "certificateOfOrigin": {
                    "id": instance.document_number
                }
            }
        else:
            data = instance.raw_certificate_data.copy()
        data.update({
            "id": instance.pk,
        })
        # data["certificateOfOrigin"].update({
        #     "issueDateTime": instance.created_at,
        #     "isPreferential": instance.type == Document.TYPE_PREF_COO,
        #     "exportCountry": str(instance.sending_jurisdiction),
        #     "importCountry": str(instance.importing_country),
        # })
        # attachments = []
        # for file in instance.files.all():
        #     rendered = file.metadata.copy()
        #     rendered.update({
        #         "filename": file.filename,
        #         "type": file.mimetype(),
        #         "data": base64.b64encode(file.file.read()).decode("utf-8")
        #     })
        #     attachments.append(rendered)

        pdf_attach = instance.get_pdf_attachment()
        if pdf_attach:
            try:
                data['certificateOfOrigin']['attachedFile'] = {
                    "file": base64.b64encode(pdf_attach.file.read()).decode("utf-8"),
                    "encodingCode": "base64",
                    "mimeCode": pdf_attach.mimetype(),
                }
            except Exception as e:
                logger.exception(e)
                pass

        # OA details
        if instance.oa:
            data["OA"] = {
                "url": instance.oa.url_repr(),
                "qrcode": instance.oa.get_qr_image_base64(),
            }
        return data

    def validate(self, data):
        cert_data = data["raw_certificate_data"].get("certificateOfOrigin")
        if not self.instance and "freeTradeAgreement" not in cert_data:
            raise serializers.ValidationError({"freeTradeAgreement": "Required field"})
        if "freeTradeAgreement" in cert_data:
            if not FTA.objects.filter(name=cert_data["freeTradeAgreement"]).exists():
                ftas = ', '.join(FTA.objects.all().values_list('name', flat=True))
                raise serializers.ValidationError(
                    {"freeTradeAgreement": f"Doesn't exist in the system, possible choices are {ftas}"}
                )
        return data

    def to_internal_value(self, data):
        """
        Proxy the certificate data (raw, mostly unparsed) to the
        instance's "raw_certificate_data" field, picking out something
        insteresting to us
        """
        super().to_internal_value(data)  # just to run the validations
        ret = {
            "raw_certificate_data": data,
        }
        if not self.instance or not self.instance.pk:
            cert_data = data.get("certificateOfOrigin") or {}
            supplyChainConsignment = cert_data.get("supplyChainConsignment", {})
            ret.update({
                "type": (
                    Document.TYPE_PREF_COO
                    if cert_data.get("isPreferential")
                    else Document.TYPE_NONPREF_COO
                ),
                "document_number": cert_data.get("id"),
                "sending_jurisdiction": supplyChainConsignment.get("exportCountry", {}).get("code"),
                "importing_country": supplyChainConsignment.get("importCountry", {}).get("code"),
            })

            if not isinstance(ret["sending_jurisdiction"], str) or len(ret["sending_jurisdiction"]) != 2:
                raise serializers.ValidationError({"exportCountry": "must be a dict with code key"})
            if not isinstance(ret["importing_country"], str) or len(ret["importing_country"]) != 2:
                raise serializers.ValidationError({"importCountry": "must be a dict with code key"})

        return ret

    def create(self, validated_data):
        create_kwargs = validated_data.copy()
        create_kwargs.pop("id", None)
        create_kwargs["created_by_user"] = self.user
        create_kwargs["created_by_org"] = self.org
        create_kwargs["oa"] = OaDetails.retrieve_new(
            for_org=self.org
        )

        # some business logic - propagating some fields to the model instance
        cert_data = validated_data["raw_certificate_data"]["certificateOfOrigin"]
        if "freeTradeAgreement" in cert_data:
            create_kwargs["fta"] = FTA.objects.filter(
                name=cert_data["freeTradeAgreement"]
            ).first()

        obj = Document.objects.create(
            **create_kwargs
        )

        try:
            issuer_id = cert_data.get("issuer", {}).get("id") or ""
            if ":" in issuer_id:
                issuer_id = issuer_id.rsplit(":", maxsplit=1)[1]
            obj.issuer, _ = Party.objects.get_or_create(
                name=cert_data.get("issuer", {}).get("name"),
                business_id=issuer_id,
            )
        except Exception as e:
            logger.exception(e)
            raise serializers.ValidationError({"issuer": "Can't parse"})

        try:
            supplyChainConsignment = cert_data.get("supplyChainConsignment", {})
            consignor = supplyChainConsignment.get("consignor", {})
            if consignor:
                exporter_bid = consignor.get("id") or ""
                if ":" in exporter_bid:
                    exporter_bid = exporter_bid.rsplit(":", maxsplit=1)[1]
                obj.exporter, _ = Party.objects.get_or_create(
                    name=consignor.get("name"),
                    business_id=exporter_bid,
                )
            obj.importer_name = supplyChainConsignment.get("consignee", {}).get("name") or ""
        except Exception as e:
            logger.exception(e)
            raise serializers.ValidationError({"supplyChainConsignment": "Can't parse consignor or consignee"})
        obj.save()
        return obj

    def update(self, instance, validated_data):
        dict_merge(instance.raw_certificate_data, validated_data["raw_certificate_data"])
        cert_data = validated_data["raw_certificate_data"].get("certificateOfOrigin") or {}
        if "name" in cert_data:
            instance.document_number = cert_data["name"]
        if "freeTradeAgreement" in cert_data:
            fta = FTA.objects.filter(
                name=cert_data["freeTradeAgreement"]
            ).first()
            if fta:
                instance.fta = fta
            else:
                raise Exception("Unknown FTA")
        instance.save()
        return instance
