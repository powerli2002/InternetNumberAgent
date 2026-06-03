# 互联网号码注册信息库



所属章节：3.2 互联网号码资源数据库



互联网号码注册信息库包含RIR最初分配给成员的IP地址和AS编号的注册详细信息。它显示了哪些组织或个人目前拥有哪些互联网号码资源，分配时间和联系方式。信息库中的这些详细信息由 RIR和这些资源的注册人共同维护。信息库还包含注册人从这些资源中进行的子分配和分配的详细信息、对此信息进行更改的日期，并且还提供了一些历史信息。这些信息主要使用inetnum/inetnum6和aut-num对象保存互联网号码资源信息。aut-num对象在数据库中有双重用途。作为RIPE互联网号码注册的一部分，它包含由RIPE NCC分配的自治系统号码 资源的注册详细信息。作为Internet路由注册表的一部分，它允许发布路由策略。它指的是一组具有单一且明确定义的外部路由策略的IP网络，由一个或多个网络运营商——自治系统运营。

inetnum/inetnum6对象包含有关分配和分配IPv4地址和IPv6空间资源的信息，是互联网号码资源信息库的主要元素之一，其主要属性见表 3.6。

inetnum对象涵盖了信息库中的许多不同类型的数据，以层次结构排列，反映了IP地址分配的层次化链条。可以以分配形式进行分区以匹配成员组织的业务结构，或者可以将其中的一部分再分配给另一个组织，最后，它的任何部分都可以分配给最终用户。同样，指派是层次结构的该部分的最低级别或终点。所有这些级别都可以通过状态值来识别。inetnum对象使用mntner对象进行保护，如果对象在对象中包含对mntner 的引用，则对象受mntner保护。这是通过包含“mnt-by:”属性来完成的。其他“mnt-xxx:”属性提供分级保护。“mnt-by:”属性在所有对象类型中都是强制性的。“mnt-lower:”、“mnt-routes:”和“mnt-domains:”属性都提供分层授权。当一个对象中包含多个值时，它们也适用于逻辑“或”。在这些属性有效的对象描述中描述了如何使用它们。inetnum对象数据案例见图 3.3。

person对象提供有关真实人物的信息，以admin-c或者tech-c引入引用。最初的意图是，这应该只用于负责与信息库中注册的互联网资源相关的技术或管理问题的联系人。然而，许多资源拥有者使用的商业模式也是记录已分配资源的最终用户客户。其目的之一被定义为资源管理人员的联系人数据库。person对象包括了技术人员或管理人员的详细信息，主要属性包括有person、address、country和nic-hdl等，各字段对应的含义如表 3.7所示。person对象数据案例见图 3.4。

表 3.6 inetnum/inetnum6对象属性

属性名

属性含义

属性类型

inetnum/

inetnum6

地址对象的IPv6地址空间范围，该范围可以是一个或多个地址。

强制属性

netname

IP 地址空间范围的名称。

强制属性

descr

对inet6num中显示的前缀的所属组织的描述。

强制属性

country

admin-c所在国家或经济体的两字母ISO 3166代码。

强制属性

org

持有此资源的组织机构ID，此ID指向organization对象。

强制属性

admin-c

相关管理负责人员ID，此ID指向person对象。

强制属性

tech-c

相关技术负责人员的ID，此ID指向person或role对象。

强制属性

abuse-c

一个滥用联系人对象，维护的邮箱允许发送有关滥用行为、安全问题等的手动或自动报告。

强制属性

status

地址分配的状态，分配、子分配或者指派等。

强制属性

mnt-by

用于授权和验证对此对象的更改的已注册的“mntner”对象。

强制属性

mnt-irt

已注册“mntner”对象的标识符，用于提供有关计算机安全事件响应小组 (CSIRT) 的信息。

强制属性

last-modified

系统生成的时间戳，用于反映上次修改对象的时间。

强制属性

source

数据来源。

强制属性

geoloc

此网络用户所在位置的纬度/经度坐标。

可选属性

language

两字母ISO 639-1 表示该网络的用户可以理解的语言。

可选属性

remarks

一般评论信息。

可选属性

notify

应将此对象的更改通知发送到的电子邮件地址。

可选属性

mnt-lower

若维护者有等级制度，则mnt-lower 与“mnt-by”一起使用。

可选属性

mnt-routes

已注册“mntner”对象的标识符，用于控制与 inet6num 对象指定的地址范围关联的“route6”对象的创建。

可选属性

inet6num:2001:0DB8::/32netname:EXAMPLENET-APdescr:Example net Pty Ltdcountry:APadmin-c:DE345-APtech-c:DE345-APstatus:ALLOCATED PORTABLEnotify:abc@examplenet.commnt-by:MAINT-EXAMPLENET-APmnt-lower:MAINT-EXAMPLENET-APmnt-routes:MAINT-EXAMPLENET-APmnt-irt:IRT-EXAMPLENET-APlast-modified:2018-08-30T07:50:19Z 20101231source:APNICinet6num:2001:0DB8::/32netname:EXAMPLENET-APdescr:Example net Pty Ltdcountry:APadmin-c:DE345-APtech-c:DE345-APstatus:ALLOCATED PORTABLEnotify:abc@examplenet.commnt-by:MAINT-EXAMPLENET-APmnt-lower:MAINT-EXAMPLENET-APmnt-routes:MAINT-EXAMPLENET-APmnt-irt:IRT-EXAMPLENET-APlast-modified:2018-08-30T07:50:19Z 20101231source:APNIC

inet6num:2001:0DB8::/32

netname:EXAMPLENET-AP

descr:Example net Pty Ltd

country:AP

admin-c:DE345-AP

tech-c:DE345-AP

status:ALLOCATED PORTABLE

notify:abc@examplenet.com

mnt-by:MAINT-EXAMPLENET-AP

mnt-lower:MAINT-EXAMPLENET-AP

mnt-routes:MAINT-EXAMPLENET-AP

mnt-irt:IRT-EXAMPLENET-AP

last-modified:2018-08-30T07:50:19Z 20101231

source:APNIC

inet6num:2001:0DB8::/32

netname:EXAMPLENET-AP

descr:Example net Pty Ltd

country:AP

admin-c:DE345-AP

tech-c:DE345-AP

status:ALLOCATED PORTABLE

notify:abc@examplenet.com

mnt-by:MAINT-EXAMPLENET-AP

mnt-lower:MAINT-EXAMPLENET-AP

mnt-routes:MAINT-EXAMPLENET-AP

mnt-irt:IRT-EXAMPLENET-AP

last-modified:2018-08-30T07:50:19Z 20101231

source:APNIC

图 3.3 inet6num对象实例

表 3.7 person字段含义表

字段名

字段含义

属性类型

person

管理、技术或区域联系人的全名。

强制属性

address

此人的完整邮政地址。

强制属性

phone

此人的电话号码。

强制属性

email

此人的电子邮箱。

强制属性

nic-hdl

数据库生成的NIC柄，唯一标识。

强制属性

mnt-by

用于授权和验证对此对象的更改的已注册的“mntner”对象。

强制属性

last-modified

系统生成的时间戳，用于反映上次修改对象的时间

强制属性

source

数据来源。

强制属性

country

所在国家或经济体的两个字母ISO 3166代码。

可选属性

fax-no

组织业务的传真号码。

可选属性

remarks

一般评论信息。

可选属性

notify

应将此对象的更改通知发送到的电子邮件地址。

可选属性

图 3.4person:Albert Brooke Crichtonaddress:123 Example st.address:20097 Exampletowncountry:AUphone:+12 34 567890 000 fax-no:+12 34 567890 010e-mail:abc@examplenet.comnic-hdl:ABC123-APnotify:abc@examplenet.commnt-byMAINT-EXAMPLENET-APlast-modified2018-08-30T07:50:19Zsource:APNICperson:Albert Brooke Crichtonaddress:123 Example st.address:20097 Exampletowncountry:AUphone:+12 34 567890 000 fax-no:+12 34 567890 010e-mail:abc@examplenet.comnic-hdl:ABC123-APnotify:abc@examplenet.commnt-byMAINT-EXAMPLENET-APlast-modified2018-08-30T07:50:19Zsource:APNIC person对象案例

person:Albert Brooke Crichton

address:123 Example st.

address:20097 Exampletown

country:AU

phone:+12 34 567890 000

fax-no:+12 34 567890 010

e-mail:abc@examplenet.com

nic-hdl:ABC123-AP

notify:abc@examplenet.com

mnt-byMAINT-EXAMPLENET-AP

last-modified2018-08-30T07:50:19Z

source:APNIC

person:Albert Brooke Crichton

address:123 Example st.

address:20097 Exampletown

country:AU

phone:+12 34 567890 000

fax-no:+12 34 567890 010

e-mail:abc@examplenet.com

nic-hdl:ABC123-AP

notify:abc@examplenet.com

mnt-byMAINT-EXAMPLENET-AP

last-modified2018-08-30T07:50:19Z

source:APNIC

图 3.5organization:ORG-APNIC1-APorg-name:Asia Pacific Network Information Centredescr:Regional Internet Registry for the Asia Pacific regioncountry:AUaddress:6 Cordelia Street, South Brisbane, QLD 4101, Australiaphone:+61 7 3858 3100fax-no:+61 7 3858 3199e-mail:helpdesk@apnic.netmnt-ref:APNIC-HMnotify:helpdesk@apnic.netmnt-by:APNIC-HMlast-modified:2018-08-30T07:50:19ZSource:APNICorganization:ORG-APNIC1-APorg-name:Asia Pacific Network Information Centredescr:Regional Internet Registry for the Asia Pacific regioncountry:AUaddress:6 Cordelia Street, South Brisbane, QLD 4101, Australiaphone:+61 7 3858 3100fax-no:+61 7 3858 3199e-mail:helpdesk@apnic.netmnt-ref:APNIC-HMnotify:helpdesk@apnic.netmnt-by:APNIC-HMlast-modified:2018-08-30T07:50:19ZSource:APNIC organization对象案例

organization:ORG-APNIC1-AP

org-name:Asia Pacific Network Information Centre

descr:Regional Internet Registry for the Asia Pacific region

country:AU

address:6 Cordelia Street, South Brisbane, QLD 4101, Australia

phone:+61 7 3858 3100

fax-no:+61 7 3858 3199

e-mail:helpdesk@apnic.net

mnt-ref:APNIC-HM

notify:helpdesk@apnic.net

mnt-by:APNIC-HM

last-modified:2018-08-30T07:50:19Z

Source:APNIC

organization:ORG-APNIC1-AP

org-name:Asia Pacific Network Information Centre

descr:Regional Internet Registry for the Asia Pacific region

country:AU

address:6 Cordelia Street, South Brisbane, QLD 4101, Australia

phone:+61 7 3858 3100

fax-no:+61 7 3858 3199

e-mail:helpdesk@apnic.net

mnt-ref:APNIC-HM

notify:helpdesk@apnic.net

mnt-by:APNIC-HM

last-modified:2018-08-30T07:50:19Z

Source:APNIC

组织对象提供有关已在信息库中注册 Internet 资源的组织的信息。这可能是一家公司、非营利组织或个人。它是作为一种将与一个组织相关的所有人力资源和互联网资源链接在一起的方法而引入的。该对象是管理信息库中数据的中心起点。所有其他对象都与此对象相关。如管理任何资源的任何方面，应该有一个组织对象，以便其他人知道是谁、维护什么以及如何联系。组织对象应该只包含业务信息。即使该组织是个人，也不应包含任何个人信息。属性主要有organization、org-name、address和e-mail等，各字段对应的含义如表 3.8所示。organization对象案例如图 3.5。

表 3.8 organization字段含义表

字段名

字段含义

属性类型

organization

组织机构对象的标识符。

强制属性

org-name

组织机构的名称。

强制属性

country

admin-c所在国家或经济体的两个字母ISO 3166代码。

强制属性

address

组织机构的完整邮政地址。

强制属性

e-mail

业务电子邮箱。

强制属性

mnt-ref

一个滥用联系人对象。

强制属性

mnt-by

用于授权和验证对此对象的更改的已注册的“mntner”对象。

强制属性

last-modified

系统生成的时间戳，用于反映上次修改对象的时间。

强制属性

source

数据来源。

强制属性

descr

组织的简短描述。

可选属性

phone

业务电话。

可选属性

fax-no

组织业务的传真号码。

可选属性

org

持有此资源组织机构ID，此ID指向organization对象。

可选属性

admin-c

相关管理负责人员ID，此ID指向person对象。

可选属性

tech-c

相关技术负责人员的ID，此ID指向person或role对象。

可选属性

ref-nfy

添加或删除对组织对象的引用时将发送通知的电子邮件地址。

可选属性

notify

应将此对象的更改通知发送到的电子邮件地址。

可选属性
