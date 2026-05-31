# 互联网路由注册信息库



所属章节：3.2 互联网号码资源数据库



互联网路由注册信息库（Internet Routing Registry ，简称IRR）是全球分布的数据库的一部分，网络运营商可以通过该数据库发布他们的路由策略和路由公告，以便其他网络运营商可以使用这些数据。IRR成立于1995年，其目的是通过在网络运营商之间共享信息来确保整个互联网路由的稳定性和一致性。IRR 实际上由几个数据库组成，网络运营商在这些数据库中发布他们的路由策略和路由公告，以便其他网络运营商可以使用这些数据。IRR包含以通用格式发布的路由和路由策略，网络运营商可以使用这些格式来配置其主干路由器，主要作用包括：

路由过滤

可以根据注册的路由过滤流量，防止因意外或恶意路由通告引起的网络问题。对等点同意仅根据注册路由进行过滤的对等网络。如果一个对等体的路由没有注册，它将被过滤。提供商和客户网络，其中提供商保护其网络免受其客户的意外路由通告。客户必须在提供商之前注册其路线。

网络故障排除

网络故障排除路由注册表可以更轻松地识别网络外部的路由问题。使用与有问题的路由关联的 ASN 的联系人来解决流量问题。

路由器配置

使用IRRToolset等工具可以创建路由器配置。对CIDR聚合以及检查 aut-num对象及其路由。

互联网全局视图

如果所有网络都在IRR中注册了它们的路由，则可以映射路由策略的全局视图。这种全球图景可以显着提高全球互联网路由的完整性。

负责存储路由注册信息的对象主要包括aut-num对象、route\route6对象、as-set对象、route-set对象等。aut-num对象在数据库中有双重用途。作为互联网号码注册信息库的一部分，它包含由分配的自治系统号码资源的注册详细信息。作为互联网路由注册表的一部分，它允许发布路由策略。它指的是一组具有单一且明确定义的外部路由策略的IP网络，由一个或多个网络运营商——自治系统运营。这是在信息库中跨越这两个注册表的唯一主要对象。aut-num对象的主要属性见表 3.9。aut-num对象案例如图 3.6。

表 3.9 aut-num对象属性

字段名

字段含义

属性类型

aut-num

自治系统编号。

强制属性

as-nam

AS的描述性名称。

强制属性

org

持有此资源组织机构ID，此ID指向organization对象。

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

mnt-by

用于授权和验证对此对象的更改的已注册的“mntner”对象。

强制属性

last-modified

系统生成的时间戳，用于反映上次修改对象的时间。

强制属性

source

数据来源。

强制属性

country

admin-c所在国家或经济体的两字母ISO 3166代码。

可选属性

member-of

引用这个AS希望成为其成员的集合对象。

可选属性

import

指定AS的路由策略。

可选属性

mp-import

指定AS的多播路由策略。

可选属性

export

指定AS的路由策略。

可选属性

mp-export

指定AS的多播路由策略。

可选属性

default

指定AS的路由策略。

可选属性

mp-default

指定AS的多播路由策略。

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

路由维护对象。

可选属性

图 3.6aut-num:AS64496as-name:AS-EXAMPLENETdescr:ASN for Example Net Pty Ltdcountry:AUorg:ORG-EXAMPLENET-APimport:AS64500export:AS64494admin-c:DE345-APtech-c:DE345-APabuse-c:DE345-APnotify:noc@example.commnt-lower:MAINT-EXAMPLENET-APmnt-routes:MAINT-EXAMPLENET-APmnt-by:MAINT-EXAMPLENET-APmnt-irt:IRT-EXAMPLENET-APlast-modified:2018-08-30T07:50:19Zsource:APNICrole:           D EXAMPLENETADMINaddress:        123 Example st.address:        20097 Exampletowncountry:        AUphone:          +12 34 567890 000fax-no:         +12 34 567890 010e-mail:         noc@examplenet.comadmin-c:        ABC123-APtech-c:         ABC123-AP       nic-hdl:        DE345-APremarks:        http://www.examplenet.com.aunotify:         hostmaster@examplenet.com.aumnt-by:         MAINT-EXAMPLENET-APlast-modified:  2018-08-30T07:50:19Z             source:         APNICaut-num:AS64496as-name:AS-EXAMPLENETdescr:ASN for Example Net Pty Ltdcountry:AUorg:ORG-EXAMPLENET-APimport:AS64500export:AS64494admin-c:DE345-APtech-c:DE345-APabuse-c:DE345-APnotify:noc@example.commnt-lower:MAINT-EXAMPLENET-APmnt-routes:MAINT-EXAMPLENET-APmnt-by:MAINT-EXAMPLENET-APmnt-irt:IRT-EXAMPLENET-APlast-modified:2018-08-30T07:50:19Zsource:APNICrole:           D EXAMPLENETADMINaddress:        123 Example st.address:        20097 Exampletowncountry:        AUphone:          +12 34 567890 000fax-no:         +12 34 567890 010e-mail:         noc@examplenet.comadmin-c:        ABC123-APtech-c:         ABC123-AP       nic-hdl:        DE345-APremarks:        http://www.examplenet.com.aunotify:         hostmaster@examplenet.com.aumnt-by:         MAINT-EXAMPLENET-APlast-modified:  2018-08-30T07:50:19Z             source:         APNIC aut-num对象案例

aut-num:AS64496

as-name:AS-EXAMPLENET

descr:ASN for Example Net Pty Ltd

country:AU

org:ORG-EXAMPLENET-AP

import:AS64500

export:AS64494

admin-c:DE345-AP

tech-c:DE345-AP

abuse-c:DE345-AP

notify:noc@example.com

mnt-lower:MAINT-EXAMPLENET-AP

mnt-routes:MAINT-EXAMPLENET-AP

mnt-by:MAINT-EXAMPLENET-AP

mnt-irt:IRT-EXAMPLENET-AP

last-modified:2018-08-30T07:50:19Z

source:APNIC

role:           D EXAMPLENETADMIN

address:        123 Example st.

address:        20097 Exampletown

country:        AU

phone:          +12 34 567890 000

fax-no:         +12 34 567890 010

e-mail:         noc@examplenet.com

admin-c:        ABC123-AP

tech-c:         ABC123-AP

nic-hdl:        DE345-AP

remarks:        http://www.examplenet.com.au

notify:         hostmaster@examplenet.com.au

mnt-by:         MAINT-EXAMPLENET-AP

last-modified:  2018-08-30T07:50:19Z

source:         APNIC

aut-num:AS64496

as-name:AS-EXAMPLENET

descr:ASN for Example Net Pty Ltd

country:AU

org:ORG-EXAMPLENET-AP

import:AS64500

export:AS64494

admin-c:DE345-AP

tech-c:DE345-AP

abuse-c:DE345-AP

notify:noc@example.com

mnt-lower:MAINT-EXAMPLENET-AP

mnt-routes:MAINT-EXAMPLENET-AP

mnt-by:MAINT-EXAMPLENET-AP

mnt-irt:IRT-EXAMPLENET-AP

last-modified:2018-08-30T07:50:19Z

source:APNIC

role:           D EXAMPLENETADMIN

address:        123 Example st.

address:        20097 Exampletown

country:        AU

phone:          +12 34 567890 000

fax-no:         +12 34 567890 010

e-mail:         noc@examplenet.com

admin-c:        ABC123-AP

tech-c:         ABC123-AP

nic-hdl:        DE345-AP

remarks:        http://www.examplenet.com.au

notify:         hostmaster@examplenet.com.au

mnt-by:         MAINT-EXAMPLENET-AP

last-modified:  2018-08-30T07:50:19Z

source:         APNIC

其中aut-num对象的"import"，"export"和"default"字段指定AS的路由策略，具体案列见图 3.7。图 3.7所示路由策略，AS4为AS5，AS10提供中转，AS4向AS123提供本地路由。

图 3.7 路由策略

路由对象route\route6包含IPv4地址空间资源的路由信息。这是互联网路由注册信息库的的主要元素之一。可以使用 IPv4地址的路由对象指定由自治系统发起的每个interAS 路由（也称为域间路由）。路由对象的主要属性见表 3.10。

路由对象的实际的案例见图 3.8。

route6:2001:0DB8::/32descr:route object for 2001:0DB8::/32origin:AS1234mnt-lower:MAINT-EXAMPLENET-APmnt-routes:MAINT-EXAMPLENET-APmnt-by:MAINT-EXAMPLENET-APlast-modified:2018-08-30T07:50:19Zsource:APNICroute6:2001:0DB8::/32descr:route object for 2001:0DB8::/32origin:AS1234mnt-lower:MAINT-EXAMPLENET-APmnt-routes:MAINT-EXAMPLENET-APmnt-by:MAINT-EXAMPLENET-APlast-modified:2018-08-30T07:50:19Zsource:APNIC图 3.8 route6对象案例

route6:2001:0DB8::/32

descr:route object for 2001:0DB8::/32

origin:AS1234

mnt-lower:MAINT-EXAMPLENET-AP

mnt-routes:MAINT-EXAMPLENET-AP

mnt-by:MAINT-EXAMPLENET-AP

last-modified:2018-08-30T07:50:19Z

source:APNIC

route6:2001:0DB8::/32

descr:route object for 2001:0DB8::/32

origin:AS1234

mnt-lower:MAINT-EXAMPLENET-AP

mnt-routes:MAINT-EXAMPLENET-AP

mnt-by:MAINT-EXAMPLENET-AP

last-modified:2018-08-30T07:50:19Z

source:APNIC

使用路由对象来帮助配置网络的路由器。route对象与aut-num和其他相关对象相结合，可用于以紧凑的形式描述您的路由策略。与读取长配置文件相比，这可以帮助网络更轻松地识别路由策略错误和遗漏。

as-set对象允许将具有相似属性的AS编号分组。可以引用单个as- set对象，而不是在aut-num对象的导入和导出属性中引用许多单独的AS编号。as-set对象属性见表 3.11。as-set案例见图 3.9。

表 3.10 route6字段含义表

字段名

字段含义

属性类型

route6

IPv6路由前缀。

强制属性

descr

与对象相关的简短描述。

强制属性

origin

前缀归属的的AS编号。

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

admin-c所在国家或经济体的两字母ISO 3166代码。

可选属性

holes

通过IPv6路由不可达的地址前缀。

可选属性

member of

标识一个route-set对象，此route6对象为其成员。

可选属性

inject

指定哪些路由器执行聚合以及何时执行聚合。

可选属性

aggr-mtd

指定路由聚合的生成方式。

可选属性

aggr-bndry

构成聚合边界的自治系统的集合。

可选属性

export-comps

指定RPSL过滤器，用于匹配需要导出到聚合边界外的更具体路由。

可选属性

components

用来组成聚合的组件路由。

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

已注册的mntner对象的标识符，用于控制比该route6对象更具体的route6对象的创建

可选属性

route-set对象是一组路由前缀，而不是一组数据库路由对象。集合可以用分层名称构建，也可以包括对其他集合的直接引用。也可以通过使用“mbrs-by-ref:”属性间接进行引用。route-set对象属性见表 3.12。route-set案例见图 3.10。

表 3.11 as-set字段含义表

字段名

字段含义

属性类型

as-set

一组aut-num对象的名字

强制属性

descr

与对象相关的简短描述

强制属性

tech-c

相关技术负责人员的ID，此ID指向person或role对象

强制属性

admin-c

相关管理负责人员ID，此ID指向person对象

强制属性

mnt-by

用于授权和验证对此对象的更改的已注册的“mntner”对象

强制属性

last-modified

系统生成的时间戳，用于反映上次修改对象的时间

强制属性

source

数据来源

强制属性

country

admin-c所在国家或经济体的两字母ISO 3166代码

可选属性

members

as-set的成员，可以是AS号或AS组

可选属性

mbrs-by-ref

已注册的“mntner”对象的标识符，用于间接向as-set添加成员

可选属性

remarks

一般评论信息

可选属性

notify

应将此对象的更改通知发送到的电子邮件地址

可选属性

mnt-lower

若维护者有等级制度，则mnt-lower 与“mnt-by”一起使用

可选属性

as-set:     AS12345:AS-EXAMPLENETdescr: EXAMPLENET-AS-SETcountry:AUmembers: AS6789, AS9876remarks: Peering AStech-c: DE345-APadmin-c: DE345-APnotify: noc@examplenet.commnt-by: MAINT-EXAMPLENET-APlast-modified: 2018-08-30T07:50:19Zsource: APNICas-set:     AS12345:AS-EXAMPLENETdescr: EXAMPLENET-AS-SETcountry:AUmembers: AS6789, AS9876remarks: Peering AStech-c: DE345-APadmin-c: DE345-APnotify: noc@examplenet.commnt-by: MAINT-EXAMPLENET-APlast-modified: 2018-08-30T07:50:19Zsource: APNIC图 3.9 as-set对象案例

as-set:     AS12345:AS-EXAMPLENET

descr: EXAMPLENET-AS-SET

country:AU

members: AS6789, AS9876

remarks: Peering AS

tech-c: DE345-AP

admin-c: DE345-AP

notify: noc@examplenet.com

mnt-by: MAINT-EXAMPLENET-AP

last-modified: 2018-08-30T07:50:19Z

source: APNIC

as-set:     AS12345:AS-EXAMPLENET

descr: EXAMPLENET-AS-SET

country:AU

members: AS6789, AS9876

remarks: Peering AS

tech-c: DE345-AP

admin-c: DE345-AP

notify: noc@examplenet.com

mnt-by: MAINT-EXAMPLENET-AP

last-modified: 2018-08-30T07:50:19Z

source: APNIC

表 3.12 route-set对象含义表

字段名

字段含义

属性类型

route-set

一组route-set的名字。

强制属性

descr

与对象相关的简短描述。

强制属性

tech-c

相关技术负责人员的ID，此ID指向person或role对象。

强制属性

admin-c

相关管理负责人员ID，此ID指向person对象。

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

members

组成route-set的AS成员。

可选属性

mbrs-by-ref

已注册的“mtnner”对象的标识符，用于间接向route-set添加成员。

可选属性

member-of

标识此route-set所属的route-set对象。

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

route-set:AS1:RS-CUSTOMERSdescr:EXAMPLEmembers:202.137.181.0/22, 203.1.0.0/24, 203.2.0.0/23tech-c:        DE345-APadmin-c:       DE345-APnotify:        abc@examplenet.commnt-by:        MAINT-EXAMPLENET-APmnt-lower:     MAINT-EXAMPLENET-APlast-modified: 2018-08-30T07:50:19Zsource:APNICroute-set:AS1:RS-CUSTOMERSdescr:EXAMPLEmembers:202.137.181.0/22, 203.1.0.0/24, 203.2.0.0/23tech-c:        DE345-APadmin-c:       DE345-APnotify:        abc@examplenet.commnt-by:        MAINT-EXAMPLENET-APmnt-lower:     MAINT-EXAMPLENET-APlast-modified: 2018-08-30T07:50:19Zsource:APNIC

route-set:AS1:RS-CUSTOMERS

descr:EXAMPLE

members:202.137.181.0/22, 203.1.0.0/24, 203.2.0.0/23

tech-c:        DE345-AP

admin-c:       DE345-AP

notify:        abc@examplenet.com

mnt-by:        MAINT-EXAMPLENET-AP

mnt-lower:     MAINT-EXAMPLENET-AP

last-modified: 2018-08-30T07:50:19Z

source:APNIC

route-set:AS1:RS-CUSTOMERS

descr:EXAMPLE

members:202.137.181.0/22, 203.1.0.0/24, 203.2.0.0/23

tech-c:        DE345-AP

admin-c:       DE345-AP

notify:        abc@examplenet.com

mnt-by:        MAINT-EXAMPLENET-AP

mnt-lower:     MAINT-EXAMPLENET-AP

last-modified: 2018-08-30T07:50:19Z

source:APNIC

图 3.10 route-set对象案例

互联网号码注册信息库对象和互联网路由注册信息库对象之间存在链接，以便授权创建这些route对象。因此，原始ASN必须在信息库中表示。数据对象的关联关系类似传统数据库中的ER图，相互之间穿插引用，甚至包含层次关系。如intetnum和route的对象，主键可能不完全对齐，甚至存在包括关系，这种关系一定程度上反映了地址的分配关系和使用关系。关系图见图 3.11。

图 3.11 对象间关系
