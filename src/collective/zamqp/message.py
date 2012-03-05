# -*- coding: utf-8 -*-
###
# collective.zamqp
#
# Licensed under the GPL license, see LICENCE.txt for more details.
#
# Copyright by Affinitic sprl
# Copyright (c) 2012 University of Jyväskylä
###
"""Transaction aware AMQP message wrapper"""

import grokcore.component as grok

from zope.interface import implements, implementedBy
from zope.component import IFactory, queryUtility
from zope.component.interfaces import ObjectEvent

from collective.zamqp.interfaces import\
    IMessage, IMessageArrivedEvent, ISerializer
from collective.zamqp.transactionmanager import VTM

import logging
logger = logging.getLogger('collective.zamqp')


class Message(object, VTM):
    """A message that can be transaction aware"""

    implements(IMessage)

    header_frame = None
    method_frame = None
    channel = None
    tx_select = False

    state = None
    acknowledged = None

    _serialized_body = None
    _deserialized_body = None

    def __init__(self, body=None, header_frame=None,
                 method_frame=None, channel=None, tx_select=None):

        self._serialized_body = body
        self._deserialized_body = None

        self.header_frame = header_frame
        self.method_frame = method_frame
        self.channel = channel

        if tx_select is not None:
            self.tx_select = tx_select

        self.state = 'RECEIVED'
        self.acknowledged = False

    @property
    def body(self):
        if not self._deserialized_body:
            # de-serializer body when its content_type is supported
            content_type = getattr(self.header_frame, "content_type", None)
            util = queryUtility(ISerializer, name=content_type)
            if util:
                self._deserializd_body =\
                    util.deserialize(self._serialized_body)
        return self._deserialized_body or self._serialized_body

    def ack(self):
        """Mark the message as acknowledge.

        If the message is registered in a transaction, we defer transmition of
        acknowledgement.

        If the message is not registered in a transaction, we transmit
        acknowledgement immediately."""

        if not self.acknowledged and not self.registered():
            self._ack()
        self.acknowledged = True

    def _ack(self):
        if self.channel:
            self.channel.basic_ack(
                delivery_tag=self.method_frame.delivery_tag)
            self.state = 'ACK'

        if self.channel and self.tx_select:
            self.channel.tx_commit()  # min support for transactional channel

        logger.info("Handled message '%s' (status = '%s')",
                    self.method_frame.delivery_tag, self.state)

    def _abort(self):
        self.state = 'RECEIVED'
        self.acknowledged = False

        # on transactional channel, rollback on abort
        if self.channel and self.tx_select:
            self.channel.tx_rollback()  # min support for transactional channel

    def _finish(self):
        if self.acknowledged and not self.state == 'ACK':
            self._ack()

    def __getattr__(self, name):
        if hasattr(self.__class__, name):
            return object.__getattribute__(self, name)
        else:
            return getattr(self.body, name)

    def sortKey(self, *ignored):
        return '~zamqp 9'  # always be the last one!


class MessageFactory(object):
    grok.implements(IFactory)

    title = u'Message Factory'
    description = u'Help creating a new message'

    def getInterfaces(self):
        return implementedBy(Message)

    def __call__(self, body=None, header_frame=None,
                 method_frame=None, channel=None, tx_select=None):
        return Message(body=body, header_frame=header_frame,
                       method_frame=method_frame, channel=channel,
                       tx_select=tx_select)

grok.global_utility(MessageFactory, provides=IFactory, name='AMQPMessage')


class MessageArrivedEvent(ObjectEvent):
    """A message has been received"""

    implements(IMessageArrivedEvent)


class MessageArrivedEventFactory(object):
    grok.implements(IFactory)

    title = u'Message Arrived Event Factory'
    description = u'Help creating a new message arrived event'

    def getInterfaces(self):
        return implementedBy(MessageArrivedEvent)

    def __call__(self, message=None):
        return MessageArrivedEvent(message)

grok.global_utility(MessageArrivedEventFactory, provides=IFactory,
                    name='AMQPMessageArrivedEvent')